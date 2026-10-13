#!/usr/bin/env python
"""Django's command-line utility for administrative tasks."""
import os
import sys


class StderrFilter:
    def __init__(self, original):
        self.original = original

    def write(self, data):
        if not isinstance(data, str):
            return self.original.write(data)
        if 'GLib-GIO-WARNING' in data and 'has no verbs' in data:
            return
        self.original.write(data)

    def writelines(self, lines):
        for line in lines:
            self.write(line)

    def flush(self):
        self.original.flush()

    def isatty(self):
        return self.original.isatty()

    def fileno(self):
        return self.original.fileno()


def main():
    """Run administrative tasks."""
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'FERREELECTRI_PLUS.settings')
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc

    if len(sys.argv) > 1 and sys.argv[1] in {'migrate', 'makemigrations'}:
        sys.stderr = StderrFilter(sys.stderr)

    execute_from_command_line(sys.argv)


if __name__ == '__main__':
    main()
