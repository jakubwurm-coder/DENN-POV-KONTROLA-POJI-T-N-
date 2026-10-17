# Polling and completed-file transfers stay responsive while XLSX runs in its own process.
workers = 1
worker_class = "gthread"
threads = 4
timeout = 180
graceful_timeout = 30
