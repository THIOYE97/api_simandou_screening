# Procfile — utilisé par Render / Heroku / Railway.
# Pour le déploiement Docker, voir Dockerfile + docker-entrypoint.sh.

release: alembic upgrade head
web: gunicorn app.main:app --bind 0.0.0.0:$PORT --workers ${GUNICORN_WORKERS:-4} --worker-class uvicorn.workers.UvicornWorker --timeout ${GUNICORN_TIMEOUT:-60} --graceful-timeout 30 --keep-alive 5 --max-requests 1000 --max-requests-jitter 100 --access-logfile - --error-logfile -
worker: celery -A app.core.celery_app:celery_app worker --loglevel=info --concurrency=${CELERY_CONCURRENCY:-4}
