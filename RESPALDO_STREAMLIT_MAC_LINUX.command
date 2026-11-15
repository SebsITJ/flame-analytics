#!/bin/bash
cd "$(dirname "$0")"
echo "FLAME IN FREEFALL - OCEANPIXELS. No cierres esta ventana mientras uses la app."
export PATH="$HOME/.local/bin:$PATH"
if ! command -v uv >/dev/null 2>&1; then
  echo "Instalando uv (solo la primera vez)..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi
echo "Preparando la app. La primera vez puede tardar de 1 a 5 minutos..."
( for i in $(seq 1 300); do
    if curl -s http://localhost:8501/_stcore/health >/dev/null 2>&1; then
      open http://localhost:8501 2>/dev/null || xdg-open http://localhost:8501 2>/dev/null
      break
    fi
    sleep 2
  done ) &
uv run streamlit run app.py --server.headless true --server.port 8501
