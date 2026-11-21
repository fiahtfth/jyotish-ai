"""SPECIAL hooks for intents whose answer is not a plain T/N template (spec Part 3).

Each hook is small and delegates to an existing engine module; special.dispatch routes by
the intent config's `hooks` list."""
