pkill gunicorn
pkill python3

git pull

# Check if git pull was successful
if [ $? -ne 0 ]; then
    echo "Git pull failed. Exiting startup script." >&2
    exit 1
fi

GUNICORN_PATH="gunicorn"
PYTHON_PATH="python3"
MANAGE_PY="./manage.py"

# --- Collect static files ---
echo "Starting Django-Q cluster..."
nohup "$PYTHON_PATH" "$MANAGE_PY" collectstatic --noinput

# --- Update git version in code ---
echo "Updating git version in code..."
"$PYTHON_PATH" "$MANAGE_PY" get_git_version > /dev/null 2>&1

# --- Start Gunicorn in the background ---
echo "Starting Web Server (Gunicorn)..."
nohup "$GUNICORN_PATH" fursvp.wsgi:application --bind 0.0.0.0:8003 >> fursvp.log 2>&1 &

# Get the PID of the last background command (Gunicorn)
GUNICORN_PID=$!
echo "Gunicorn started with PID: $GUNICORN_PID"

# --- Start Django-Q cluster in the background ---
echo "Starting Django-Q cluster..."
nohup "$PYTHON_PATH" "$MANAGE_PY" qcluster >> qcluster.log 2>&1 &

# Get the PID of the last background command (Django-Q cluster)
QCLUSTER_PID=$!
echo "Django-Q cluster started with PID: $QCLUSTER_PID"

echo "FURsvp server and Django-Q cluster initiated."