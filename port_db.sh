GUNICORN_PATH="gunicorn"
PYTHON_PATH="python3"
MANAGE_PY="./manage.py"

"$PYTHON_PATH" "$MANAGE_PY" makemigrations
"$PYTHON_PATH" "$MANAGE_PY" migrate