#!/bin/sh
set -e

case "$1" in
  daphne|python)
    python manage.py migrate --noinput
    python manage.py collectstatic --noinput
    ;;
esac

exec "$@"
