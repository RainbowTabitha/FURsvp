GUNICORN_PATH="gunicorn"
PYTHON_PATH="python3"
MANAGE_PY="./manage.py"

# --- Start Gunicorn in the background ---
echo "Starting Web Server (Gunicorn)..."
nohup "$GUNICORN_PATH" FursVP.wsgi:application --bind 0.0.0.0:80 >> gunicorn.log 2>&1 &

# Get the PID of the last background command (Gunicorn)
GUNICORN_PID=$!
echo "Gunicorn started with PID: $GUNICORN_PID"

# --- Start Django-Q cluster in the background ---
echo "Starting Django-Q cluster..."
nohup "$PYTHON_PATH" "$MANAGE_PY" qcluster >> qcluster.log 2>&1 &

# Get the PID of the last background command (Django-Q cluster)
QCLUSTER_PID=$!
echo "Django-Q cluster started with PID: $QCLUSTER_PID"

echo "FursVP server and Django-Q cluster initiated." 