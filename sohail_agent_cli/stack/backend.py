"""Backend stack skeletons."""

from __future__ import annotations

from collections import OrderedDict
from pathlib import Path


class BackendSkeletons:
    """Create backend-only technology skeletons."""

    def generate(self, technology: str | None) -> OrderedDict[Path, str]:
        """Generate backend files for a normalized technology name."""
        if technology == "node":
            return self._node()
        if technology == "fastapi":
            return self._fastapi()
        if technology == "django":
            return self._django()
        if technology == "go":
            return self._go()
        return OrderedDict()

    @staticmethod
    def _node() -> OrderedDict[Path, str]:
        files: OrderedDict[Path, str] = OrderedDict()
        files[Path("backend/package.json")] = """{
  "scripts": {
    "dev": "node src/server.js",
    "start": "node src/server.js"
  },
  "dependencies": {
    "express": "latest"
  },
  "devDependencies": {}
}
"""
        files[Path("backend/src/server.js")] = """const express = require("express");

const app = express();
const port = process.env.PORT || 3000;

app.use(express.json());

app.listen(port, () => {
  console.log(`Node stack skeleton listening on port ${port}`);
});
"""
        files[Path("backend/routes/.gitkeep")] = ""
        files[Path("backend/controllers/.gitkeep")] = ""
        files[Path("backend/middleware/.gitkeep")] = ""
        return files

    @staticmethod
    def _fastapi() -> OrderedDict[Path, str]:
        files: OrderedDict[Path, str] = OrderedDict()
        files[Path("backend/requirements.txt")] = "fastapi\nuvicorn[standard]\n"
        files[Path("backend/main.py")] = """from fastapi import FastAPI

app = FastAPI(title="Stack Skeleton")
"""
        files[Path("backend/app/__init__.py")] = ""
        files[Path("backend/routers/.gitkeep")] = ""
        files[Path("backend/models/.gitkeep")] = ""
        return files

    @staticmethod
    def _django() -> OrderedDict[Path, str]:
        files: OrderedDict[Path, str] = OrderedDict()
        files[Path("backend/manage.py")] = """#!/usr/bin/env python
import os
import sys


def main() -> None:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "app.settings")
    from django.core.management import execute_from_command_line

    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
"""
        files[Path("backend/requirements.txt")] = "django\n"
        files[Path("backend/app/__init__.py")] = ""
        files[Path("backend/app/settings.py")] = """SECRET_KEY = "replace-me"
DEBUG = True
ROOT_URLCONF = "app.urls"
INSTALLED_APPS = []
MIDDLEWARE = []
ALLOWED_HOSTS = []
"""
        files[Path("backend/app/urls.py")] = """from django.urls import path

urlpatterns = []
"""
        files[Path("backend/app/wsgi.py")] = """import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "app.settings")

application = get_wsgi_application()
"""
        return files

    @staticmethod
    def _go() -> OrderedDict[Path, str]:
        files: OrderedDict[Path, str] = OrderedDict()
        files[Path("backend/go.mod")] = """module stack-skeleton

go 1.22
"""
        files[Path("backend/cmd/server/main.go")] = """package main

import "fmt"

func main() {
	fmt.Println("Go stack skeleton")
}
"""
        files[Path("backend/internal/.gitkeep")] = ""
        return files
