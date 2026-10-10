"""Habit Quest - turn real-world habits into an RPG character.

A tiny, dependency-free Python package that powers the local web app:

    data.py    static game content (stats, archetypes, shop, achievements)
    engine.py  pure rules: XP curve, rewards, power, achievements
    store.py   SQLite persistence + state assembly
    api.py     JSON API routes
    server.py  http.server wiring for the API + static assets
"""

__version__ = "1.0.0"
