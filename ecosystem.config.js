// PM2 ecosystem file — usado na VPS para manter o processo rodando
module.exports = {
  apps: [
    {
      name: "cotacoes-api",
      script: "main.py",
      interpreter: "python3",
      instances: 1,          // NUNCA usar mais de 1 (fila SSE em memória)
      autorestart: true,
      watch: false,
      max_memory_restart: "400M",
      env: {
        APP_ENV: "production",
        APP_PORT: 8000,
      },
      log_date_format: "YYYY-MM-DD HH:mm:ss",
      out_file: "logs/pm2-out.log",
      error_file: "logs/pm2-err.log",
      merge_logs: true,
    },
  ],
};
