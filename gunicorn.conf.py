# Generování kompletního XLSX auditu může překročit výchozích 30 sekund.
# Používá se existujícím startovacím příkazem: gunicorn app:app.
timeout = 180
graceful_timeout = 30
