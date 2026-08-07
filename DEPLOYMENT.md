# Bot V3 — Production Deployment Guide

## 🚀 Quick Start (Docker Compose)

### 1. Setup Environment Variables

```bash
cp .env.example .env
nano .env  # Edit dengan credentials Anda
```

**Required Variables:**
```bash
POLYMARKET_API_KEY=your_api_key
POLYMARKET_API_SECRET=your_api_secret
POLYMARKET_API_PASSPHRASE=your_passphrase
POLYMARKET_PRIVATE_KEY=your_private_key
GRAFANA_ADMIN_PASSWORD=secure_password
TELEGRAM_BOT_TOKEN=optional_bot_token
TELEGRAM_CHAT_ID=optional_chat_id
```

### 2. Configure Bot V3

Edit `config/config.yaml`:
```yaml
guardrail:
  mode: risk_free_only  # WAJIB untuk live!
  max_imbalance_shares: 14

capital:
  initial_capital_usd: 1000.0

schedule:
  taker_until_s: 295
  maker_only_below_s: 60
```

### 3. Start All Services

```bash
docker-compose up -d
```

This starts:
- **Bot V3 Control Plane** (port 8000, 9090)
- **Market Worker** (auto-scaled to 2 replicas)
- **Prometheus** (port 9091)
- **Grafana** (port 3000)
- **Redis** (port 6379)

### 4. Access Dashboards

| Service | URL | Credentials |
|---------|-----|-------------|
| FastAPI Docs | http://localhost:8000/docs | - |
| Prometheus | http://localhost:9091 | - |
| Grafana | http://localhost:3000 | admin / your_password |
| Redis CLI | localhost:6379 | - |

### 5. Verify Health

```bash
curl http://localhost:8000/health
```

Expected response:
```json
{"status": "healthy", "version": "3.0.0"}
```

---

## 📊 Monitoring Setup

### Prometheus Metrics

Bot V3 exports metrics at `http://localhost:9090/metrics`:

```bash
# View raw metrics
curl http://localhost:9090/metrics

# Query specific metric
curl 'http://localhost:9091/api/v1/query?query=bot_pnl_realized'
```

**Key Metrics:**
- `bot_pnl_realized` — Realized PnL (USD)
- `bot_pnl_current{market="..."}` — Unrealized PnL per market
- `bot_orders_total` — Total orders placed
- `bot_fills_total` — Total fills received
- `bot_guardrail_rejections_total` — Guardrail rejections
- `bot_worker_status{market="..."}` — Worker status (0/1)
- `bot_imbalance{market="..."}` — Inventory imbalance

### Grafana Dashboard

1. Login to Grafana: http://localhost:3000
2. Navigate to **Dashboards → Bot V3 → Overview**
3. Default dashboard includes:
   - Realized & Unrealized PnL
   - Active Workers count
   - Inventory Imbalance by Market
   - Orders vs Fills rate
   - Guardrail Rejections
   - Order Latency (p95)

**Import Custom Dashboard:**
```bash
# Copy dashboard JSON to Grafana
docker cp monitoring/grafana/dashboards/bot_v3_overview.json \
  bot-v3-grafana:/etc/grafana/provisioning/dashboards/

# Restart Grafana
docker-compose restart grafana
```

### Alerting Rules

Create `/workspace/monitoring/prometheus_alerts.yml`:

```yaml
groups:
  - name: bot-v3-alerts
    rules:
      - alert: HighImbalance
        expr: bot_imbalance > 14
        for: 1m
        labels:
          severity: warning
        annotations:
          summary: "High inventory imbalance detected"
          
      - alert: GuardrailRejectionSpike
        expr: rate(bot_guardrail_rejections_total[5m]) > 10
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "Guardrail rejecting too many orders"
          
      - alert: WorkerDown
        expr: bot_worker_status == 0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "Market worker stopped"
```

---

## 🔧 Manual Deployment (Without Docker)

### 1. Install Dependencies

```bash
pip install -r requirements.txt
pip install -r requirements-prod.txt
```

### 2. Run Bot V3

```bash
# Set environment variables
export POLYMARKET_API_KEY=your_key
export POLYMARKET_API_SECRET=your_secret
export POLYMARKET_API_PASSPHRASE=your_passphrase
export POLYMARKET_PRIVATE_KEY=your_private_key

# Start FastAPI Control Plane
uvicorn main_v3:app --host 0.0.0.0 --port 8000 --workers 2

# In separate terminal, start Market Worker
python -m src.workers.market_worker
```

### 3. Start Prometheus

```bash
prometheus --config.file=monitoring/prometheus.yml
```

Access at: http://localhost:9090

### 4. Start Grafana

```bash
grafana-server --config=/etc/grafana/grafana.ini
```

Access at: http://localhost:3000

---

## 🛡️ Security Best Practices

### 1. Never Commit Secrets

```bash
# Add to .gitignore
.env
config/*.yaml
*.key
*.pem
```

### 2. Use Environment Variables

```yaml
# ❌ Bad: Hardcoded secrets
polymarket:
  api_key: sk_live_abc123

# ✅ Good: Environment variables
polymarket:
  api_key: ${POLYMARKET_API_KEY}
```

### 3. Enable HTTPS in Production

```bash
# Use nginx reverse proxy with Let's Encrypt
sudo apt install nginx certbot python3-certbot-nginx

sudo certbot --nginx -d your-domain.com
```

### 4. Firewall Rules

```bash
# Allow only necessary ports
sudo ufw allow 22/tcp    # SSH
sudo ufw allow 443/tcp   # HTTPS
sudo ufw deny 8000/tcp   # Block direct API access
sudo ufw enable
```

---

## 📈 Scaling Strategy

### Horizontal Scaling (Workers)

```bash
# Scale workers based on number of markets
docker-compose up -d --scale market-worker=5
```

**Recommendation:**
- 1 worker per 5-10 markets
- Max 10 workers per Control Plane

### Vertical Scaling (Resources)

Edit `docker-compose.yml`:

```yaml
deploy:
  resources:
    limits:
      cpus: '4.0'     # Increase for more markets
      memory: 4G      # Increase for larger buffers
```

### Load Balancing

For high-traffic deployments:

```yaml
# Add nginx load balancer
nginx:
  image: nginx:alpine
  ports:
    - "80:80"
  volumes:
    - ./nginx.conf:/etc/nginx/nginx.conf
  depends_on:
    - bot-v3
```

---

## 🔄 CI/CD Pipeline

### GitHub Actions Workflow

The `.github/workflows/ci-cd.yml` pipeline:

1. **Test**: Run unit tests + linting
2. **Build**: Build Docker images
3. **Push**: Push to GitHub Container Registry
4. **Deploy**: Deploy to production (manual approval)

### Setup Required Secrets

In GitHub repository settings → Secrets:

```
PROD_SERVER_HOST=your.server.ip
PROD_SERVER_USER=deploy
PROD_SERVER_SSH_KEY=<ssh_private_key>
TELEGRAM_BOT_TOKEN=optional
TELEGRAM_CHAT_ID=optional
```

### Manual Deployment

```bash
# Pull latest changes
git pull origin master

# Rebuild and restart
docker-compose pull
docker-compose up -d --force-recreate

# Cleanup old images
docker system prune -f
```

---

## 🐛 Troubleshooting

### Bot Won't Start

```bash
# Check logs
docker-compose logs bot-v3

# Common issues:
# 1. Missing environment variables
# 2. Invalid config.yaml syntax
# 3. Port already in use
```

### Metrics Not Showing

```bash
# Verify metrics endpoint
curl http://localhost:8000/metrics

# Check Prometheus targets
# Visit: http://localhost:9091/targets
```

### Worker Crashes

```bash
# Check worker logs
docker-compose logs market-worker

# Restart worker
docker-compose restart market-worker

# Scale down and up
docker-compose up -d --scale market-worker=0
docker-compose up -d --scale market-worker=2
```

### High Latency

```bash
# Check order latency metric
curl 'http://localhost:9091/api/v1/query?query=histogram_quantile(0.95, rate(bot_order_latency_seconds_bucket[5m]))'

# If > 1s:
# 1. Reduce number of markets per worker
# 2. Increase worker CPU allocation
# 3. Check network connectivity to Polymarket
```

---

## 📝 Maintenance

### Daily Checks

- [ ] Review Grafana dashboard for anomalies
- [ ] Check realized PnL vs expected
- [ ] Verify all workers are running
- [ ] Monitor guardrail rejections

### Weekly Tasks

- [ ] Review logs for errors
- [ ] Update dependencies (`pip install -U -r requirements.txt`)
- [ ] Backup configuration files
- [ ] Test failover procedures

### Monthly Tasks

- [ ] Security audit (update OS packages)
- [ ] Performance review (latency metrics)
- [ ] Capacity planning (scale if needed)
- [ ] Documentation update

---

## 🆘 Support

### Documentation
- [Arsitektur Bot v3](./Arsitektur_Bot_v3.txt)
- [CONFIG.md](./CONFIG.md)
- [GUIDELINE_DUAL_SIDE_REGIME.md](./GUIDELINE_DUAL_SIDE_REGIME.md)

### Logs Location
```bash
# Docker logs
docker-compose logs -f bot-v3
docker-compose logs -f market-worker

# File logs (if configured)
tail -f logs/bot-v3.log
tail -f logs/market-worker.log
```

### Emergency Stop

```bash
# Stop all services
docker-compose down

# Stop specific service
docker-compose stop bot-v3

# Remove all containers and volumes
docker-compose down -v
```

---

## ✅ Pre-Launch Checklist

Before going live:

- [ ] Guardrail mode set to `risk_free_only`
- [ ] All secrets stored in environment variables
- [ ] HTTPS enabled for public endpoints
- [ ] Monitoring dashboards configured
- [ ] Alerting rules tested
- [ ] Backup strategy in place
- [ ] Rollback procedure documented
- [ ] Team trained on emergency procedures

**⚠️ WARNING**: Mode `off` dilarang untuk live trading! 85.4% market Bonereaper bukan risk-free.
