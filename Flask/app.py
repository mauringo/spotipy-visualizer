import os
from pathlib import Path
from urllib.parse import urlsplit

from flask import Flask
from theme import register_theme
from spotify_player import PlayerError, default_data_dir, register_player


def create_app(data_dir=None):
    app = Flask(__name__)
    data_dir = Path(data_dir) if data_dir else default_data_dir()
    register_player(app, data_dir)
    register_theme(app, data_dir)

    @app.get('/')
    def index():
        return app.send_static_file('index.html')

    return app


if __name__ == '__main__':
    from waitress import serve
    proxy = os.environ.get('TRUSTED_PROXY')
    port = int(os.environ.get('PORT', '60123'))
    app = create_app()
    player = app.extensions['spotify_player']
    auth_url = f'http://127.0.0.1:{port}/auth/login'
    try:
        callback = urlsplit(player.oauth().redirect_uri)
        auth_url = f'{callback.scheme}://{callback.netloc}/auth/login'
    except PlayerError:
        print(f'Spotify configuration required: {player.data_dir / "spotify.ini"}', flush=True)
    print(f'Local player: http://127.0.0.1:{port}', flush=True)
    print(f'Spotify authentication: {auth_url}', flush=True)
    host = os.environ.get('HOST', '0.0.0.0')
    print(f'Listening on {host}:{port}', flush=True)
    if host == '0.0.0.0':
        print(f'Network player: http://<server-LAN-IP>:{port}', flush=True)
    serve(app, host=host,
          port=port, trusted_proxy=proxy,
          trusted_proxy_headers={'x-forwarded-proto'} if proxy else set())
