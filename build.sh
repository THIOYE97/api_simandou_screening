#!/usr/bin/env bash
set -e
pip install -r requirements.txt
# Pré-télécharge les modèles EasyOCR au build
python -c "import easyocr; easyocr.Reader(['fr', 'en'], gpu=False)"
echo "✅ EasyOCR models ready"