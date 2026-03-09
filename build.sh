#!/usr/bin/env bash
set -e

# Installer Tesseract via sudo (nécessaire sur Render)
sudo apt-get update -qq
sudo apt-get install -y -qq tesseract-ocr tesseract-ocr-fra tesseract-ocr-eng

# Vérification
tesseract --version

# Installer les dépendances Python
pip install -r requirements.txt