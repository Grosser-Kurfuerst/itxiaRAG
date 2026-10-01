"""只验证真实 HTTP 协议，不下载模型、不声称已验证语义质量。"""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from embeddings.openai_compatible import OpenAICompatibleEmbedding

pytestmark = pytest.mark.integration


def test_embedding_http_protocol():
    requests = []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            requests.append((self.path, payload))
            result = {'data': [{'index': i, 'embedding': [1.0, 0.0]} for i, _ in enumerate(payload['input'])]}
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(result).encode())

    server = HTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        provider = OpenAICompatibleEmbedding(base_url=f'http://127.0.0.1:{server.server_port}/v1',
                                             model='test', dimensions=2, revision='v1', query_prefix='query: ')
        assert provider.embed_documents(['a', 'b']) == [[1.0, 0.0]] * 2
        assert provider.embed_query('电池') == [1.0, 0.0]
        assert requests[0][0] == '/v1/embeddings'
        assert requests[1][1]['input'] == ['query: 电池']
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
