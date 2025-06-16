#!/bin/bash

# 🔍 Crypto Alert Bot - Container Diagnostic Script
# Identifica quale container è il bot crypto

set -euo pipefail

# Colori
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
log_warning() { echo -e "${YELLOW}[WARNING]${NC} $1"; }

echo "🔍 CRYPTO BOT CONTAINER DIAGNOSTIC"
echo "=================================="

# Lista tutti i container
log_info "Container disponibili:"
echo ""
docker ps -a --format "table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}"
echo ""

# Analizza ogni container per trovare il bot crypto
log_info "Analizzando container per identificare il bot crypto..."
echo ""

containers=($(docker ps -a --format '{{.Names}}'))

for container in "${containers[@]}"; do
    echo "🔍 Analizzando: $container"
    echo "----------------------------------------"
    
    # Controlla immagine
    image=$(docker inspect "$container" --format '{{.Config.Image}}' 2>/dev/null || echo "unknown")
    echo "📦 Immagine: $image"
    
    # Controlla se ha file Python del bot
    if docker exec "$container" test -f "/app/bot.py" 2>/dev/null; then
        echo "✅ Trovato bot.py"
        LIKELY_BOT=true
    elif docker exec "$container" ls /app/ 2>/dev/null | grep -q "\.py"; then
        echo "✅ Trovati file Python"
        LIKELY_BOT=true
    else
        echo "❌ Nessun file bot.py"
        LIKELY_BOT=false
    fi
    
    # Controlla environment variables crypto-related
    if docker exec "$container" printenv 2>/dev/null | grep -q "TELEGRAM_TOKEN"; then
        echo "✅ Trovato TELEGRAM_TOKEN"
        LIKELY_BOT=true
    else
        echo "❌ Nessun TELEGRAM_TOKEN"
    fi
    
    # Controlla database crypto
    if docker exec "$container" find /app -name "subs.db" -o -name "*.db" 2>/dev/null | grep -q ".db"; then
        echo "✅ Trovato database"
        LIKELY_BOT=true
    else
        echo "❌ Nessun database"
    fi
    
    # Controlla logs per keywords crypto
    if docker logs "$container" --tail=20 2>/dev/null | grep -i -E "(crypto|bitcoin|telegram|bot|price|alert)" >/dev/null; then
        echo "✅ Log contengono keywords crypto"
        LIKELY_BOT=true
    else
        echo "❌ Log non crypto-related"
    fi
    
    # Verifica finale
    if [ "$LIKELY_BOT" = true ]; then
        log_success "🎯 QUESTO SEMBRA IL BOT CRYPTO!"
        
        echo ""
        echo "📋 Dettagli completi:"
        echo "   Nome: $container"
        echo "   Immagine: $image"
        echo "   Status: $(docker inspect "$container" --format '{{.State.Status}}')"
        
        # Mostra environment variables importanti
        echo ""
        echo "🔧 Environment variables:"
        docker exec "$container" printenv 2>/dev/null | grep -E "(TELEGRAM|CHECK|ADMIN)" | head -5 || echo "   Nessuna variabile trovata"
        
        # Mostra file principali
        echo ""
        echo "📁 File nella directory /app:"
        docker exec "$container" ls -la /app/ 2>/dev/null | head -10 || echo "   Impossibile accedere a /app"
        
        # Mostra logs recenti
        echo ""
        echo "📝 Log recenti (ultimi 5):"
        docker logs "$container" --tail=5 2>/dev/null || echo "   Nessun log disponibile"
        
        FOUND_BOT_CONTAINER="$container"
    else
        log_warning "❓ Non sembra il bot crypto"
    fi
    
    echo ""
    echo "----------------------------------------"
    echo ""
done

# Risultato finale
if [ -n "${FOUND_BOT_CONTAINER:-}" ]; then
    echo ""
    log_success "🎯 BOT CRYPTO IDENTIFICATO: $FOUND_BOT_CONTAINER"
    echo ""
    echo "Per fare l'upgrade, modifica lo script upgrade.sh:"
    echo "Cambia: OLD_CONTAINER_NAME=\"crypto-alert-bot\""
    echo "Con:    OLD_CONTAINER_NAME=\"$FOUND_BOT_CONTAINER\""
    echo ""
    echo "Oppure lancia direttamente:"
    echo "sed -i 's/crypto-alert-bot/$FOUND_BOT_CONTAINER/g' upgrade.sh"
    echo "./upgrade.sh"
    
else
    log_warning "❓ Nessun container bot crypto identificato chiaramente"
    echo ""
    echo "💡 Controlla manualmente:"
    echo "   docker exec [container_name] ls /app/"
    echo "   docker logs [container_name] --tail=10"
    echo "   docker exec [container_name] printenv | grep TELEGRAM"
fi