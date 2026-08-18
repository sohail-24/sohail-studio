import os
from http.server import SimpleHTTPRequestHandler, HTTPServer

class Handler(SimpleHTTPRequestHandler):
    def translate_path(self, path):
        if path == '/':
            return os.path.join(os.getcwd(), 'dashboard', 'index.html')
        elif path.startswith('/assets/'):
            # The path starts with /assets/ e.g., /assets/app.js
            # Maps to dashboard/app.js
            return os.path.join(os.getcwd(), 'dashboard', path[8:])
        return super().translate_path(path)

print("Serving on 8000...")
HTTPServer(('', 8000), Handler).serve_forever()
