import http.server
import socketserver
import os

PORT = 8001
DIRECTORY = os.path.join(os.path.dirname(os.path.dirname(__file__)), "tests")

class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=DIRECTORY, **kwargs)

if __name__ == "__main__":
    print(f"Serving Mock Job Application at http://localhost:{PORT}/mock_form.html")
    with socketserver.TCPServer(("", PORT), Handler) as httpd:
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nMock server stopped.")
