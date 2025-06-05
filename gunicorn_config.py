# Gunicorn configuration
workers = 4
worker_class = 'sync'
worker_connections = 1000
timeout = 30
keepalive = 5
threads = 3
bind = '0.0.0.0:10000'
