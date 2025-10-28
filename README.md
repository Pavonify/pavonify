# Pavonify

## Trophy System

Seed initial trophies:

```bash
python manage.py seed_trophies
```

Evaluate trophies for all users:

```bash
python manage.py evaluate_trophies
```

## Live Practice Competition

The live practice feature relies on Django Channels with a Redis backend. Provide the
following environment variables when running locally or deploying:

```
REDIS_URL=redis://localhost:6379/0
GAME_PIN_LENGTH=6
QUESTION_TIME_DEFAULT=20
GAME_MAX_CLASS_SIZE=200
```

Start the development server with the ASGI entry point to enable websocket support:

```bash
python manage.py runserver
```

Run the focused live app tests with:

```bash
python manage.py test live
```
