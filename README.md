# ChinHin-404Backend
In order to run this, you need to activate a virtual environment and download the related dependencies:
python -m venv .venv
.venv\Scripts\activate
pip install requirements.txt

After download, you may run it using (It will start the execution from main.py):
uvicorn app.main:app --reload --port 8000

---------------------------------------------------------------------------------------------------------