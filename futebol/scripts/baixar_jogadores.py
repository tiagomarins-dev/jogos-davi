#!/usr/bin/env python3
# Baixa cutouts de jogadores da API TheSportsDB e gera a base do jogo.
# Uso:
#   python3 scripts/baixar_jogadores.py [--limite N] [--embutir] [--validar-lista]
# Idempotente: jogadores.json é cache de metadados; PNG existente não é re-baixado.

import argparse
import json
import os
import re
import sys
import time
import unicodedata
import urllib.parse
import urllib.request

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ARQ_LISTA = os.path.join(RAIZ, "scripts", "lista-jogadores.json")
ARQ_BASE = os.path.join(RAIZ, "jogadores.json")
ARQ_INDEX = os.path.join(RAIZ, "index.html")
DIR_IMGS = os.path.join(RAIZ, "assets", "jogadores")
DIR_ESCUDOS = os.path.join(RAIZ, "assets", "escudos")
ARQ_BIOS = os.path.join(RAIZ, "scripts", "bios.json")
API_BUSCA = "https://www.thesportsdb.com/api/v1/json/3/searchplayers.php?p={}"
API_EX_TIMES = "https://www.thesportsdb.com/api/v1/json/3/lookupformerteams.php?id={}"
CORTES = [60, 100, 150, 200]
MARCA_INI = "/*JOGADORES_INICIO*/"
MARCA_FIM = "/*JOGADORES_FIM*/"
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


# Remove acentos de um texto (NFD) — usado no slug e na comparação de times
def sem_acento(texto):
    nfd = unicodedata.normalize("NFD", texto)
    return "".join(c for c in nfd if unicodedata.category(c) != "Mn")


# Gera slug seguro a partir do nome: minúsculas, sem acento, só [a-z0-9-]
def gerar_slug(nome):
    slug = re.sub(r"[^a-z0-9]+", "-", sem_acento(nome).lower()).strip("-")
    return slug


# Valida a URL do cutout: https e host do TheSportsDB (cutouts vêm de r2.thesportsdb.com)
def url_cutout_valida(url):
    try:
        p = urllib.parse.urlparse(url)
    except ValueError:
        return False
    host = (p.hostname or "").lower()
    return p.scheme == "https" and (
        host == "thesportsdb.com" or host.endswith(".thesportsdb.com")
    )


# Busca o jogador na API e escolhe o resultado certo (time ou, p/ lenda, nacionalidade)
def buscar_na_api(item):
    url = API_BUSCA.format(urllib.parse.quote(item["busca"]))
    with urllib.request.urlopen(url, timeout=15) as resp:
        dados = json.load(resp)
    resultados = dados.get("player") or []
    candidatos = [r for r in resultados if r.get("strCutout")]
    if not candidatos:
        return None, "sem resultado com cutout"
    if item["categoria"] == "lenda":
        # lenda aposentada não tem time atual — valida pela nacionalidade
        certos = [r for r in candidatos if (r.get("strNationality") or "") == "Brazil"]
    elif item.get("timeEsperado"):
        # comparação sem acento dos dois lados: API varia entre "Atlético" e "Atletico"
        alvo = sem_acento(item["timeEsperado"]).lower()
        certos = [
            r for r in candidatos
            if alvo in sem_acento(r.get("strTeam") or "").lower()
        ]
    else:
        certos = []
    if certos:
        return certos[0], None
    # fallback: 1º resultado com cutout, com aviso (pode ser transferência recente)
    return candidatos[0], "fallback: time nao bateu, usando 1o resultado"


# Baixa o cutout com validação de host e de conteúdo (magic bytes PNG)
def baixar_cutout(url, destino):
    if not url_cutout_valida(url):
        raise ValueError(f"URL de cutout invalida/nao permitida: {url}")
    tmp = destino + ".tmp"
    with urllib.request.urlopen(url, timeout=15) as resp:
        conteudo = resp.read()
    if not conteudo.startswith(PNG_MAGIC):
        raise ValueError("conteudo baixado nao e PNG")
    with open(tmp, "wb") as f:
        f.write(conteudo)
    os.replace(tmp, destino)  # rename atômico: nunca deixa PNG parcial


# Busca os times anteriores do jogador e baixa o escudo de cada um (offline)
def buscar_ex_times(id_player):
    url = API_EX_TIMES.format(id_player)
    with urllib.request.urlopen(url, timeout=15) as resp:
        dados = json.load(resp)
    registros = dados.get("formerteams") or []
    # agrupa por time: um mesmo clube pode aparecer em base (Youth) e profissional
    por_time = {}
    for reg in registros:
        nome = reg.get("strFormerTeam")
        if not nome:
            continue
        anos = [a for a in (reg.get("strJoined"), reg.get("strDeparted")) if a]
        t = por_time.setdefault(nome, {"time": nome, "anos": [], "badge": None})
        t["anos"].extend(int(a) for a in anos if a.isdigit())
        if reg.get("strBadge"):
            t["badge"] = reg["strBadge"]
    ex_times = []
    for t in sorted(por_time.values(), key=lambda x: min(x["anos"]) if x["anos"] else 9999):
        periodo = ""
        if t["anos"]:
            ini, fim = min(t["anos"]), max(t["anos"])
            periodo = str(ini) if ini == fim else f"{ini}–{fim}"
        escudo = ""
        if t["badge"] and url_cutout_valida(t["badge"]):
            escudo = gerar_slug(t["time"]) + ".png"
            destino = os.path.join(DIR_ESCUDOS, escudo)
            if not os.path.exists(destino):
                try:
                    baixar_cutout(t["badge"], destino)
                except Exception:
                    escudo = ""  # escudo é opcional: falha não derruba o jogador
        ex_times.append({"time": t["time"], "periodo": periodo, "escudo": escudo})
    return ex_times


# Valida a lista curada: duplicatas e mínimo de 4 por categoria em cada corte
def validar_lista(lista):
    erros = []
    buscas = [i["busca"] for i in lista]
    duplicadas = {b for b in buscas if buscas.count(b) > 1}
    if duplicadas:
        erros.append(f"buscas duplicadas: {sorted(duplicadas)}")
    print(f"total de jogadores na lista: {len(lista)}")
    for corte in CORTES:
        fatia = lista[:corte]
        contagem = {}
        for i in fatia:
            contagem[i["categoria"]] = contagem.get(i["categoria"], 0) + 1
        print(f"corte {corte}: {contagem}")
        for cat, qtd in contagem.items():
            if qtd < 4:
                erros.append(f"corte {corte}: categoria '{cat}' com {qtd} (< 4)")
    return erros


# Monta a base final na ORDEM da lista curada (posição = ranking de fama);
# aplica as bios curadas (scripts/bios.json) por cima — editar bio não exige re-download
def montar_base(lista, cache):
    bios = {}
    if os.path.exists(ARQ_BIOS):
        with open(ARQ_BIOS, encoding="utf-8") as f:
            bios = json.load(f)
    base = []
    for item in lista:
        slug = gerar_slug(item["nome"])
        png = os.path.join(DIR_IMGS, slug + ".png")
        if slug in cache and os.path.exists(png):
            j = dict(cache[slug])
            if bios.get(slug):
                j["bio"] = bios[slug]
            else:
                j.pop("bio", None)
            base.append(j)
    return base


# Confere se, após exclusões (sem cutout), cada corte manteve ≥4 por categoria
def validar_pool_pos_download(base):
    for corte in CORTES:
        fatia = base[:corte]
        contagem = {}
        for j in fatia:
            contagem[j["categoria"]] = contagem.get(j["categoria"], 0) + 1
        avisos = [f"{c}:{q}" for c, q in contagem.items() if q < 4]
        status = "⚠ REPOR NOMES" if avisos else "ok"
        print(f"pool {corte}: {contagem} {status}")


# Injeta o JSON da base entre os marcadores do index.html (exatamente 1 ocorrência)
def embutir(base):
    if not os.path.exists(ARQ_INDEX):
        sys.exit("ERRO: index.html nao existe ainda — crie o jogo antes de --embutir.")
    with open(ARQ_INDEX, encoding="utf-8") as f:
        html = f.read()
    if html.count(MARCA_INI) != 1 or html.count(MARCA_FIM) != 1:
        sys.exit("ERRO: marcadores JOGADORES_INICIO/FIM ausentes ou duplicados no index.html.")
    # escapa </ pra sequência </script> dentro de string nunca quebrar o HTML
    json_js = json.dumps(base, ensure_ascii=False).replace("</", "<\\/")
    ini = html.index(MARCA_INI) + len(MARCA_INI)
    fim = html.index(MARCA_FIM)
    novo = html[:ini] + f" const JOGADORES = {json_js}; " + html[fim:]
    with open(ARQ_INDEX, "w", encoding="utf-8") as f:
        f.write(novo)
    print(f"embed ok: {len(base)} jogadores injetados no index.html")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limite", type=int, help="processa so os N primeiros da lista")
    ap.add_argument("--embutir", action="store_true", help="so injeta o JSON no index.html")
    ap.add_argument("--validar-lista", action="store_true", help="so valida a lista curada")
    args = ap.parse_args()

    with open(ARQ_LISTA, encoding="utf-8") as f:
        lista = json.load(f)

    if args.validar_lista:
        erros = validar_lista(lista)
        if erros:
            sys.exit("FALHOU:\n- " + "\n- ".join(erros))
        print("lista valida ✔")
        return

    # cache: base existente indexada por slug (re-execução não perde metadados)
    cache = {}
    if os.path.exists(ARQ_BASE):
        with open(ARQ_BASE, encoding="utf-8") as f:
            cache = {j["slug"]: j for j in json.load(f)}

    if args.embutir:
        embutir(montar_base(lista, cache))
        return

    os.makedirs(DIR_IMGS, exist_ok=True)
    os.makedirs(DIR_ESCUDOS, exist_ok=True)
    processar = lista[: args.limite] if args.limite else lista
    stats = {"cache": 0, "baixados": 0, "enriquecidos": 0, "sem_cutout": [], "falhas": []}

    for item in processar:
        slug = gerar_slug(item["nome"])
        destino = os.path.join(DIR_IMGS, slug + ".png")
        # cache completo = PNG no disco + metadados + enriquecimento (exTimes) já feitos
        if slug in cache and os.path.exists(destino) and "exTimes" in cache[slug]:
            stats["cache"] += 1
            continue
        try:
            r, aviso = buscar_na_api(item)
            if r is None:
                stats["sem_cutout"].append(item["nome"])
                continue
            if aviso:
                print(f"  aviso [{item['nome']}]: {aviso} -> {r.get('strTeam')}")
            novo = not os.path.exists(destino)
            if novo:
                baixar_cutout(r["strCutout"], destino)
            # enriquecimento: times anteriores (com escudos) para o painel de leitura
            time.sleep(2)  # respeita o rate limit entre as 2 chamadas do jogador
            ex_times = buscar_ex_times(r["idPlayer"])
            cache[slug] = {
                "slug": slug,
                "nome": item["nome"],
                "time": r.get("strTeam") or "",
                "nacionalidade": r.get("strNationality") or "",
                "posicao": r.get("strPosition") or "",
                "categoria": item["categoria"],
                "nascimento": r.get("dateBorn") or "",
                "localNascimento": r.get("strBirthLocation") or "",
                "exTimes": ex_times,
                "baixadoEm": time.strftime("%Y-%m-%d"),
                "urlCutout": r["strCutout"],
            }
            if novo:
                stats["baixados"] += 1
            else:
                stats["enriquecidos"] += 1
            print(f"ok: {item['nome']} ({r.get('strTeam')}) — {len(ex_times)} ex-times")
        except Exception as e:  # 1 falha não aborta o lote
            stats["falhas"].append(f"{item['nome']}: {e}")
            print(f"  FALHA [{item['nome']}]: {e}")
        time.sleep(2)  # rate limit da chave gratuita (~30 req/min)

    base = montar_base(lista, cache)
    with open(ARQ_BASE, "w", encoding="utf-8") as f:
        json.dump(base, f, ensure_ascii=False, indent=1)

    print("\n=== RELATORIO ===")
    print(f"processados: {len(processar)} | baixados: {stats['baixados']} | enriquecidos: {stats['enriquecidos']} | cache: {stats['cache']}")
    print(f"sem cutout ({len(stats['sem_cutout'])}): {stats['sem_cutout']}")
    print(f"falhas ({len(stats['falhas'])}): {stats['falhas']}")
    validar_pool_pos_download(base)
    if os.path.exists(ARQ_INDEX):
        embutir(base)


if __name__ == "__main__":
    main()
