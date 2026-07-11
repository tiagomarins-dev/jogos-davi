#!/bin/bash
# Gera os áudios do jogo dos animais com a voz Luciana (say do macOS + ffmpeg).
# Roda 1×; re-executar só gera o que falta. Uso: bash animais/scripts/gerar_audios.sh

set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p audio

# slug|frase falada
ANIMAIS=(
  "elefante|É o elefante!"
  "girafa|É a girafa!"
  "zebra|É a zebra!"
  "vaca|É a vaca!"
  "porco|É o porco!"
  "tartaruga|É a tartaruga!"
  "dinossauro|É o dinossauro!"
  "jacare|É o jacaré!"
  "flamingo|É o flamingo!"
  "camelo|É o camelo!"
  "cachorro|É o cachorro!"
  "gato|É o gato!"
  "cavalo|É o cavalo!"
  "macaco|É o macaco!"
  "cobra|É a cobra!"
  "golfinho|É o golfinho!"
  "baleia|É a baleia!"
  "caranguejo|É o caranguejo!"
  "pato|É o pato!"
  "galo|É o galo!"
  "coruja|É a coruja!"
  "peixe|É o peixe!"
  "borboleta|É a borboleta!"
  "coelho|É o coelho!"
  "canguru|É o canguru!"
  "tubarao|É o tubarão!"
  "polvo|É o polvo!"
)

for item in "${ANIMAIS[@]}"; do
  slug="${item%%|*}"
  frase="${item#*|}"
  destino="audio/${slug}.m4a"
  if [ -f "$destino" ]; then
    echo "cache: $slug"
    continue
  fi
  tmp="$(mktemp /tmp/animal-XXXX).aiff"
  say -v Luciana "$frase" -o "$tmp"
  # aac 96k mono: ~30KB por frase, qualidade sobrando pra voz
  ffmpeg -y -loglevel error -i "$tmp" -ac 1 -c:a aac -b:a 96k "$destino"
  rm -f "$tmp"
  echo "ok: $slug"
done

echo "---"
echo "total: $(ls audio/*.m4a | wc -l | tr -d ' ') áudios em animais/audio/"
