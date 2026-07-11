# Tech Spec: Jogo "Quem é o Jogador?" — v1 MVP

**Data:** 2026-07-11
**Status:** spec pós-auditoria (substitui o plano `~/.claude/plans/planeje-a-implementacao-synchronous-heron.md`)
**Escopo desta spec:** jogo completo offline (2 modos × 4 dificuldades) + pipeline de download de imagens. Fora: publicação, novos modos, atualização automática de elencos (§13).

---

## 1. Objetivo + decisões

Jogo HTML infantil para o Davi (7-9 anos): adivinhar o jogador de futebol pela **silhueta** ou **foto embaçada**, múltipla escolha com 4 opções. Fonte de imagens: API TheSportsDB (gratuita, chave pública `3`), cutouts PNG 500×500 com fundo transparente — baixados 1× por script; o jogo roda 100% offline via `file://`.

**Decisões (usuário):**
- Múltipla escolha (4 botões), nunca digitação
- Jogadores: Europa atual + Brasileirão + seleção brasileira + lendas **somente brasileiras**
- 2 modos: silhueta / embaçado (escolha na tela inicial)
- 4 dificuldades por tamanho de pool: 60 / 100 / 150 / 200 (lista ordenada por fama)
- Entrada tripla: touch, mouse, teclado 1-4 (fileira + numpad)

**Resolução pós-auditoria (decisões desta spec):**
- **Embed do JSON** — script grava `jogadores.json` sempre; injeção no `index.html` é etapa separada `--embutir`, idempotente, executada após o HTML existir. (Corrige **C1**.)
- **Cache de metadados** — `jogadores.json` é o cache; re-execução mescla, pula API de quem já tem PNG+metadados. (Corrige **C2**.)
- **Validação de host do cutout** — `urllib.parse.urlparse`: `https` + hostname `== thesportsdb.com` ou `.endswith('.thesportsdb.com')`. Cutouts vêm de **`r2.thesportsdb.com`** (fato verificado ao vivo em 2026-07-11). (**H1**.)
- **Magic bytes PNG** + gravação `.tmp`→rename. (**M1**.)
- **≥4 jogadores por categoria em cada corte** + fallback de distratores no código. (**M2**.)
- **AudioContext resume no 1º gesto** (iPad/Safari). (**M3**.)
- **localStorage em try/catch**. (**L1**.) · **`onerror` de imagem sorteia substituto**. (**L2**.)
- **Marcadores de embed: exatamente 1 ocorrência ou falha com erro claro**. (**R1**.) · **`--validar-lista`**. (**R2**.) · **`--embutir` parcial no passo 3**. (**R3**.) · **`JOGADORES` vazio → mensagem amigável**. (**R4**.) · **Lendas com nome de registro na busca**. (**R5**.)

### Auditoria (/plan-audit 2×, 2026-07-11) — **8.7/10, APROVADO COM RESSALVAS**
1ª rodada 7.4/10 (2 críticos C1/C2 — corrigidos no plano refinado); 2ª rodada 8.7/10, 0 bloqueantes, 1 ALTO (H1) + deltas — todos incorporados acima. Projeto greenfield: não há código legado; grounding = testes ao vivo da API nesta data (busca, formato do cutout, host r2, limite de elenco) registrados em `Obsidian/Projetos/jogos-davi/investigate/20260711-jogo-quem-e-o-jogador.md`.

---

## 2. Arquitetura (fluxo completo)

```
FASE A (build, roda 1×; re-executável)
  scripts/lista-jogadores.json (curadoria, ordem = fama)
        │
        ▼
  scripts/baixar_jogadores.py
        ├── carrega cache jogadores.json (se existir) ──────────┐
        ├── p/ cada jogador SEM cache: GET searchplayers.php    │ merge
        │     ├── match: strTeam ⊇ timeEsperado (case-insens.)  │
        │     │        lendas: strNationality == "Brazil"       │
        │     ├── valida strCutout (urlparse https+host)  [H1]  │
        │     ├── baixa → .tmp → magic bytes PNG → rename [M1]  │
        │     └── sleep(2)  (rate limit ~30/min)                │
        ├── grava jogadores.json (ordem da lista curada) ◄──────┘
        ├── relatório: baixados/cache/sem-cutout/falhas + contagem por corte
        └── --embutir: injeta JSON entre /*JOGADORES_INICIO*/…/*JOGADORES_FIM*/
              no index.html (exatamente 1 ocorrência ou ERRO)   [R1]

FASE B (runtime, offline, file://)
  index.html
    telaInicial() ──escolhe──► modo (silhueta|embacado) + dificuldade (60|100|150|200)
        │  (1º gesto: iniciarAudio() → AudioContext.resume())   [M3]
        ▼
    iniciarPartida(modo, dif)
        ├── pool = JOGADORES.slice(0, dif)
        ├── rodadas = sortear 10 sem repetição
        ├── precarregarImagens(rodadas)
        └── loop 10×: mostrarRodada()
              ├── img filtro: brightness(0) | blur(18px)
              ├── montarAlternativas(): 3 distratores mesma categoria
              │     do pool; fallback outras categorias se <4   [M2]
              ├── entrada: click/touch + keydown 1-4/Numpad1-4
              │     (ignorada se rodada já respondida)
              ├── dicas: nacionalidade→posição→time
              │     pontos 100→70→50→30; blur 18→12→6 (modo embaçado)
              ├── acerto: remove filtro (transição), verde, som agudo
              ├── erro: revela, correto verde, clicado vermelho, som grave
              └── img.onerror → substituirJogador()             [L2]
        ▼
    telaFinal(): placar, faixa de mensagem, recorde
        localStorage 'quemEOJogador.recorde.<modo>.<dif>' em try/catch [L1]
```

**Idempotência/concorrência:** script re-executável (cache + `.tmp`+rename atômico + embed por substituição, nunca append). No jogo, flag `rodadaRespondida` bloqueia clique duplo e tecla repetida.

---

## 3. `scripts/lista-jogadores.json` — lista curada (criar)

Array JSON, **posição = ranking de fama** (sem campo de rank). Schema por item:

```json
{ "busca": "Vinícius Júnior", "nome": "Vini Jr", "timeEsperado": "Real Madrid", "categoria": "europa" }
```

- `busca`: nome completo p/ API (evita homônimo — "Kane" retorna Todd Kane). **Lendas: nome de registro** — "Ronaldo Nazário", "Ronaldinho Gaúcho", "Kaká", "Romário", "Roberto Carlos"… (R5)
- `timeEsperado`: substring case-insensitive do `strTeam` esperado. **Lendas: `null`** (validação por nacionalidade).
- `categoria`: `europa | brasileirao | selecao | lenda`
  - `europa` = joga fora do Brasil e não é convocado regular (Messi, CR7 entram aqui)
  - `selecao` = brasileiro atual da seleção (dentro ou fora do país): Alisson, Marquinhos, Casemiro…
  - `brasileirao` = joga no Brasil (Neymar/Santos, Arrascaeta/Flamengo…)
  - `lenda` = aposentado brasileiro

**Composição (~200):**
| Faixa | Conteúdo |
|---|---|
| 1-60 | Craques que criança vê na TV: Vini, Neymar, Mbappé, Messi, CR7, Haaland, Yamal, Bellingham…; lendas icônicas (Pelé, Ronaldo, Ronaldinho, Kaká); maiores ídolos do Brasileirão |
| 61-100 | 2º escalão da Europa, seleção atual, mais Brasileirão, demais lendas |
| 101-150 | Bons jogadores de times médios da Europa + elencos do Brasileirão |
| 151-200 | Desafio — só quem acompanha muito conhece |

**Restrição dura (M2):** cada corte (primeiros 60, 100, 150, 200) contém **≥4 jogadores de cada categoria presente nele** — senão o sorteio de 3 distratores da mesma categoria quebra. Verificada por `--validar-lista`.

**Critério de aceite:** JSON válido; ~200 itens; sem `busca` duplicada; `--validar-lista` verde.

---

## 4. `scripts/baixar_jogadores.py` — download + cache + embed (criar)

Python3 stdlib. Código completo:

```python
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
API_BUSCA = "https://www.thesportsdb.com/api/v1/json/3/searchplayers.php?p={}"
CORTES = [60, 100, 150, 200]
MARCA_INI = "/*JOGADORES_INICIO*/"
MARCA_FIM = "/*JOGADORES_FIM*/"
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


# Gera slug seguro a partir do nome: minúsculas, sem acento, só [a-z0-9-]
def gerar_slug(nome):
    nfd = unicodedata.normalize("NFD", nome)
    sem_acento = "".join(c for c in nfd if unicodedata.category(c) != "Mn")
    slug = re.sub(r"[^a-z0-9]+", "-", sem_acento.lower()).strip("-")
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
        alvo = item["timeEsperado"].lower()
        certos = [r for r in candidatos if alvo in (r.get("strTeam") or "").lower()]
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


# Valida a lista curada: duplicatas e mínimo de 4 por categoria em cada corte
def validar_lista(lista):
    erros = []
    buscas = [i["busca"] for i in lista]
    duplicadas = {b for b in buscas if buscas.count(b) > 1}
    if duplicadas:
        erros.append(f"buscas duplicadas: {sorted(duplicadas)}")
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
    processar = lista[: args.limite] if args.limite else lista
    stats = {"cache": 0, "baixados": 0, "sem_cutout": [], "falhas": []}

    for item in processar:
        slug = gerar_slug(item["nome"])
        destino = os.path.join(DIR_IMGS, slug + ".png")
        if slug in cache and os.path.exists(destino):
            stats["cache"] += 1
            continue
        try:
            r, aviso = buscar_na_api(item)
            if r is None:
                stats["sem_cutout"].append(item["nome"])
                continue
            if aviso:
                print(f"  aviso [{item['nome']}]: {aviso} -> {r.get('strTeam')}")
            if not os.path.exists(destino):
                baixar_cutout(r["strCutout"], destino)
            cache[slug] = {
                "slug": slug,
                "nome": item["nome"],
                "time": r.get("strTeam") or "",
                "nacionalidade": r.get("strNationality") or "",
                "posicao": r.get("strPosition") or "",
                "categoria": item["categoria"],
                "baixadoEm": time.strftime("%Y-%m-%d"),
                "urlCutout": r["strCutout"],
            }
            stats["baixados"] += 1
            print(f"ok: {item['nome']} ({r.get('strTeam')})")
        except Exception as e:  # 1 falha não aborta o lote
            stats["falhas"].append(f"{item['nome']}: {e}")
            print(f"  FALHA [{item['nome']}]: {e}")
        time.sleep(2)  # rate limit da chave gratuita (~30 req/min)

    base = montar_base(lista, cache)
    with open(ARQ_BASE, "w", encoding="utf-8") as f:
        json.dump(base, f, ensure_ascii=False, indent=1)

    print("\n=== RELATORIO ===")
    print(f"processados: {len(processar)} | baixados: {stats['baixados']} | cache: {stats['cache']}")
    print(f"sem cutout ({len(stats['sem_cutout'])}): {stats['sem_cutout']}")
    print(f"falhas ({len(stats['falhas'])}): {stats['falhas']}")
    validar_pool_pos_download(base)
    if os.path.exists(ARQ_INDEX):
        embutir(base)


# Monta a base final na ORDEM da lista curada (posição = ranking de fama)
def montar_base(lista, cache):
    base = []
    for item in lista:
        slug = gerar_slug(item["nome"])
        png = os.path.join(DIR_IMGS, slug + ".png")
        if slug in cache and os.path.exists(png):
            base.append(cache[slug])
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


if __name__ == "__main__":
    main()
```

**Testes do script (manuais, sem framework — projeto sem stack de testes):**
1. `--validar-lista` com lista ok → verde; com duplicata plantada → falha listando-a
2. `--limite 5` 2× seguidas → 2ª execução ~instantânea (`cache: 5`), `jogadores.json` idêntico
3. `url_cutout_valida("https://evil.com/thesportsdb.com/x.png")` → `False`; `https://r2.thesportsdb.com/...` → `True` (testar via `python3 -c`)
4. `--embutir` sem `index.html` → erro claro; com marcador duplicado → erro claro
5. `find assets/jogadores -size 0` → vazio

---

## 5. `index.html` — o jogo (criar)

Arquivo único (HTML+CSS+JS), pt-BR, sem dependência externa, abre via `file://`. Estrutura das 3 telas (`<section>` alternadas por classe `ativa`): `#tela-inicial`, `#tela-jogo`, `#tela-final`.

### 5.1 Dados embutidos + estado

```html
<script>
/*JOGADORES_INICIO*/ const JOGADORES = []; /*JOGADORES_FIM*/

// Estado global da partida
const estado = {
  modo: null,          // 'silhueta' | 'embacado'
  dificuldade: null,   // 60 | 100 | 150 | 200
  rodadas: [],         // 10 jogadores sorteados
  rodadaAtual: 0,
  pontos: 0,
  dicasUsadas: 0,      // 0-3 na rodada corrente
  respondida: false,   // trava clique duplo / tecla repetida
};
</script>
```

- **R4:** `iniciarPartida()` começa com `if (JOGADORES.length < 8) { mostrarAviso('Rode o script de download primeiro: python3 scripts/baixar_jogadores.py'); return; }` (8 = mínimo pra 10 rodadas com 4 alternativas fazer sentido; usar `Math.min(10, ...)` rodadas se pool curto).

### 5.2 Sorteio e alternativas (M2)

```javascript
// Sorteia 10 jogadores sem repetição dentro do pool dos N primeiros (N = dificuldade)
function sortearRodadas(pool) {
  const copia = [...pool];
  // Fisher-Yates parcial: embaralha e corta 10
  for (let i = copia.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [copia[i], copia[j]] = [copia[j], copia[i]];
  }
  return copia.slice(0, Math.min(10, copia.length));
}

// Monta 4 alternativas: correto + 3 distratores da mesma categoria do pool;
// se a categoria tiver menos de 4 no pool, completa com outras categorias
function montarAlternativas(certo, pool) {
  const mesmaCat = pool.filter(j => j.categoria === certo.categoria && j.slug !== certo.slug);
  const outras = pool.filter(j => j.categoria !== certo.categoria);
  const distratores = [];
  const fontes = [mesmaCat, outras];
  for (const fonte of fontes) {
    const embaralhada = [...fonte].sort(() => Math.random() - 0.5);
    for (const j of embaralhada) {
      if (distratores.length === 3) break;
      if (!distratores.some(d => d.slug === j.slug)) distratores.push(j);
    }
    if (distratores.length === 3) break;
  }
  return [certo, ...distratores].sort(() => Math.random() - 0.5);
}
```

### 5.3 Entrada tripla

```javascript
// Teclado: 1-4 da fileira e do numpad selecionam a alternativa correspondente
document.addEventListener('keydown', (ev) => {
  if (telaAtiva() !== 'jogo' || estado.respondida) return;
  let n = null;
  if (ev.key >= '1' && ev.key <= '4') n = Number(ev.key);
  if (/^Numpad[1-4]$/.test(ev.code)) n = Number(ev.code.slice(-1));
  if (n) responder(n - 1);
});
```

- Botões: `<button class="alternativa" data-indice="0">1️⃣ Vini Jr</button>` com `click` → `responder(indice)`; `responder()` primeiro checa `estado.respondida` e seta `true`.
- CSS: `.alternativa { min-height: 64px; touch-action: manipulation; font-size: 1.3rem; }` — sem delay de 300ms, dedo de criança.

### 5.4 Imagem, filtros, dicas, onerror

```css
/* Filtro do modo — remoção com transição = revelação animada */
#foto-jogador { transition: filter .8s ease; max-width: min(70vw, 340px); }
.modo-silhueta #foto-jogador { filter: brightness(0); }
.modo-embacado #foto-jogador { filter: blur(18px); }
.modo-embacado.dica-1 #foto-jogador { filter: blur(12px); }
.modo-embacado.dica-2 #foto-jogador { filter: blur(6px); }
.revelado #foto-jogador { filter: none !important; }
/* fundo claro atrás do cutout: silhueta preta não some no tema estádio */
.moldura-foto { background: radial-gradient(#f3f1ef, #d8ddee); border-radius: 16px; }
```

- **Dicas (botão "💡 Dica"):** revela em sequência nacionalidade → posição → time; pontos da rodada: `[100, 70, 50, 30][estado.dicasUsadas]`; no modo embaçado adiciona classe `dica-1`/`dica-2` (blur 12/6px). 3ª dica não reduz mais o blur (30 pontos é o piso).
- **L2:** `img.onerror = () => substituirJogador()` — sorteia outro do pool fora das rodadas já usadas, refaz alternativas, `console.warn(slug)`.
- Pré-carregar: `estado.rodadas.forEach(j => { const i = new Image(); i.src = 'assets/jogadores/' + j.slug + '.png'; })` ao iniciar a partida.

### 5.5 Som (M3) — Web Audio, resume no 1º gesto

```javascript
let ctxAudio = null;
// Cria/destrava o áudio no primeiro gesto do usuário (exigência do Safari/iPad)
function iniciarAudio() {
  if (!ctxAudio) ctxAudio = new (window.AudioContext || window.webkitAudioContext)();
  if (ctxAudio.state === 'suspended') ctxAudio.resume();
}
// Toca um bip com oscilador: acerto agudo (880Hz), erro grave (180Hz), vitória arpejo
function tocarSom(tipo) {
  if (!ctxAudio) return;
  const freqs = { acerto: [880], erro: [180], vitoria: [523, 659, 784, 1047] };
  (freqs[tipo] || []).forEach((f, i) => {
    const osc = ctxAudio.createOscillator();
    const gain = ctxAudio.createGain();
    osc.frequency.value = f;
    gain.gain.setValueAtTime(0.15, ctxAudio.currentTime + i * 0.12);
    gain.gain.exponentialRampToValueAtTime(0.001, ctxAudio.currentTime + i * 0.12 + 0.25);
    osc.connect(gain).connect(ctxAudio.destination);
    osc.start(ctxAudio.currentTime + i * 0.12);
    osc.stop(ctxAudio.currentTime + i * 0.12 + 0.3);
  });
}
```

`iniciarAudio()` chamado no handler dos botões da **tela inicial** (1º gesto garantido antes de qualquer som).

### 5.6 Recorde (L1) — localStorage blindado

```javascript
// localStorage pode lançar em file:// no modo privado do Safari — jogo segue sem recorde
function lerRecorde(modo, dif) {
  try { return Number(localStorage.getItem(`quemEOJogador.recorde.${modo}.${dif}`)) || 0; }
  catch { return 0; }
}
function salvarRecorde(modo, dif, pontos) {
  try { localStorage.setItem(`quemEOJogador.recorde.${modo}.${dif}`, String(pontos)); }
  catch { /* sem storage: ignora */ }
}
```

8 chaves possíveis (2 modos × 4 dificuldades); tela inicial mostra o recorde da combinação selecionada; tela final compara e exibe badge "🏆 NOVO RECORDE!".

### 5.7 Visual

Tema estádio: fundo gradiente verde-gramado escuro, placar eletrônico (topo: rodada X/10 + pontos, fonte monoespaçada), moldura clara atrás da foto (§5.4), emoji nos títulos. `<meta name="viewport" content="width=device-width, initial-scale=1">`. Grid das alternativas: 1 coluna em <480px, 2 colunas acima. Sem overflow horizontal em 375px.

---

## 6. Arquivos

**Criar:** `scripts/lista-jogadores.json` · `scripts/baixar_jogadores.py` · `index.html`
**Gerados:** `jogadores.json` · `assets/jogadores/*.png`
**Testes:** sem framework (adequado ao porte) — checklist manual §10 + one-liners do §4.

## 7. Sequência de implementação

1. **`scripts/lista-jogadores.json`** — curadoria primeiro: tudo depende do ranking e da restrição ≥4/categoria/corte
2. **`scripts/baixar_jogadores.py`** — antes do download em massa, rodar `--validar-lista`
3. **`--limite 10`** → conferir cutouts visualmente (recorte/silhueta reconhecível) — barato detectar problema de recorte antes dos ~200
4. **Download completo** (~7-10 min, background) — em paralelo, começar o passo 5
5. **`index.html`** — tela inicial → partida → final (marcadores de embed desde o 1º esqueleto)
6. **`--embutir`** (parcial já no passo 3 se quiser testar o jogo com 10; final após passo 4)
7. **Verificação §10** → smoke test em device real

## 8. Reuso

Projeto greenfield — sem código legado. Padrões herdados dos jogos irmãos do Davi: 1 arquivo HTML, pt-BR, sem dependências, localStorage p/ recorde, emoji na UI. Fatos de API reusados da investigação (`Obsidian/Projetos/jogos-davi/investigate/20260711-jogo-quem-e-o-jogador.md`): endpoint de busca, formato do cutout (500×500 RGBA), host `r2.thesportsdb.com`, homônimo "Kane".

## 9. Segurança (checklist)

- [ ] **H1** — `strCutout` validado via `urlparse`: `https` + hostname `thesportsdb.com`/`.thesportsdb.com`
- [ ] **M1** — magic bytes PNG + `.tmp`→rename; `find assets/jogadores -size 0` vazio
- [ ] **R1** — embed falha com erro claro se marcadores ≠ 1 ocorrência; nunca grava sem substituir
- [ ] Escape `</` → `<\/` no JSON embutido; `index.html` lido/escrito com `encoding="utf-8"`
- [ ] Slug `[a-z0-9-]`; escrita restrita a `assets/jogadores/`
- [ ] Timeout 15s em toda chamada de rede; try/except por item
- [ ] Sem `console.log` de debug remanescente (o `console.warn` do onerror fica — é diagnóstico legítimo)

## 10. Verificação (E2E)

1. `python3 scripts/baixar_jogadores.py --validar-lista` → verde (duplicatas + ≥4/categoria/corte)
2. `--limite 10` 2× → 2ª instantânea; abrir 3 PNGs e conferir transparência/recorte
3. Download completo → relatório: ≥ ~180 baixados, faltantes só lendas, contagem por corte sem `⚠`
4. `--embutir` → `grep -c "JOGADORES_INICIO" index.html` = 1; `JOGADORES.length` no console = nº do relatório
5. Abrir `index.html` via `file://` → zero console error
6. Jogar 1 partida por modo (2) e conferir 1 partida em cada dificuldade: pool de 60 nunca mostra jogador além do 60º (validar amostrando nomes exibidos)
7. Dicas: pontos 100→70→50→30; blur 18→12→6 no embaçado; 10 rodadas sem repetição; distratores sem duplicata e sem o correto
8. Teclado: fileira 1-4 e Numpad1-4 respondem; tecla após resposta é ignorada; clique duplo não conta 2×
9. Recorde: fechar/reabrir → persiste por combinação; simular storage quebrado (`Object.defineProperty(window,'localStorage',{get(){throw 0}})` num teste rápido) → jogo não morre
10. Renomear 1 PNG → onerror substitui o jogador, partida segue
11. Responsivo: 375px e 768px sem overflow horizontal, botões ≥64px (medir via DevTools)
12. Device real (tablet/celular): touch sem delay, som toca após 1º toque, silhueta legível

## 11. Riscos aceitos / documentar

- **API pode mudar/sair do ar** — aceito: jogo é offline pós-download; re-download futuro usa `urlCutout`/`baixadoEm` gravados. Falha de rede aparece no relatório, nunca corrompe a base.
- **Fallback de busca pode pegar homônimo com cutout** — mitigado por nome completo + validação de time/nacionalidade + warning no log + conferência visual (passo 3); risco residual baixo, impacto = 1 imagem errada, trivial de corrigir (deletar PNG + ajustar busca + re-rodar).
- **Recorte dos cutouts varia** (busto vs corpo inteiro) — aceito; conferência do passo 3 decide se precisa trocar jogador.
- **Direitos de imagem** — uso pessoal/local; **não publicar** sem revisar licenciamento.
- **Elencos desatualizam** (transferências) — aceito no MVP; campo `time` só aparece em dica, erro não quebra o jogo.

## 12. Fases seguintes (fora do MVP)

- Modo "quem é mais rápido": 2 jogadores alternando no mesmo device
- Atualização de elencos: re-rodar script com `--forcar` (ignora cache de metadados, mantém PNGs)
- Novos pacotes: goleiros históricos, seleções da Copa
- Estatísticas: % de acerto por jogador (localStorage), "seu carrasco"

## 13. Esforço

| Fase | Estimativa |
|---|---|
| Lista curada (~200 nomes + quotas por corte) | ~2h (domina o custo) |
| Script | ~1h |
| Download completo | ~10 min (máquina) |
| Jogo (index.html) | ~3h |
| Verificação + device real | ~1h |
| **Total** | **~7h** |
