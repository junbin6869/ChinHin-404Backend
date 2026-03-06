# ChinHin-404Backend
In order to run this, you need to activate a virtual environment and download the related dependencies:
python -m venv .venv
.venv\Scripts\activate
pip install requirements.txt

After download, you may run it using (It will start the execution from main.py):
uvicorn app.main:app --reload --port 8000 --log-level debug

-------------------------------------------------------------------------------------------------------

backup yaml:
name: Build and deploy Python app to Azure Web App - 404

on:
  push:
    branches:
      - main
  workflow_dispatch:

jobs:

  build:
    runs-on: ubuntu-latest

    steps:
      - name: Checkout repo
        uses: actions/checkout@v4

      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Install dependencies (build check)
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements.txt

      - name: Prepare deploy package
        run: |
          mkdir deploy
          cp -r app deploy/
          cp -r api deploy/ || true
          cp main.py deploy/ || true
          cp requirements.txt deploy/
          cp *.py deploy/ || true

      - name: Upload deploy artifact
        uses: actions/upload-artifact@v4
        with:
          name: deploy-package
          path: deploy


  deploy:
    runs-on: ubuntu-latest
    needs: build

    steps:
      - name: Download artifact
        uses: actions/download-artifact@v4
        with:
          name: deploy-package
          path: deploy

      - name: Show deploy files
        run: |
          echo "Deploy package:"
          ls -R deploy

      - name: Deploy to Azure Web App
        uses: azure/webapps-deploy@v3
        with:
          app-name: "404"
          slot-name: "Production"
          publish-profile: ${{ secrets.AZUREAPPSERVICE_PUBLISHPROFILE_BD038AFC9F124793B8CC2C2F26ED597C }}
          package: deploy
          clean: true