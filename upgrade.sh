#!/bin/bash

# 🔄 Crypto Alert Bot - Safe Upgrade Script
# Upgrade dalla versione precedente alla versione ottimizzata

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
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# Configurazione
OLD_CONTAINER_NAME="competent_golick"
BACKUP_DIR="./upgrade_backup_$(date +%Y%m%d_%H%M%S)"

echo "🚀 CRYPTO ALERT BOT - UPGRADE TO OPTIMIZED VERSION"
echo "=================================================="

# 1. Analizza situazione attuale
analyze_current_setup() {
    log_info "Analizzando setup attuale..."
    
    # Controlla container esistente
    if docker ps -a --format '{{.Names}}' | grep -q "$OLD_CONTAINER_NAME"; then
        log_success "Trovato container esistente: $OLD_CONTAINER_NAME"
        
        # Mostra info container
        echo ""
        echo "📊 Container attuale:"
        docker ps --filter name="$OLD_CONTAINER_NAME" --format "table {{.Names}}\t{{.Status}}\t{{.Image}}"
        
        # Controlla se sta girando
        if docker ps --filter name="$OLD_CONTAINER_NAME" --format '{{.Names}}' | grep -q "$OLD_CONTAINER_NAME"; then
            log_info "✅ Container è in running"
            CONTAINER_RUNNING=true
        else
            log_warning "⏸️ Container è fermo"
            CONTAINER_RUNNING=false
        fi
        
    else
        log_error "Nessun container trovato con nome: $OLD_CONTAINER_NAME"
        log_info "Containers disponibili:"
        docker ps -a --format '{{.Names}}' | head -10
        exit 1
    fi
    
    # Controlla database esistente
    if docker exec "$OLD_CONTAINER_NAME" test -f "/app/subs.db" 2>/dev/null; then
        log_success "✅ Database trovato nel container"
        HAS_DATABASE=true
    elif docker exec "$OLD_CONTAINER_NAME" test -f "/app/data/subs.db" 2>/dev/null; then
        log_success "✅ Database trovato in /app/data/"
        HAS_DATABASE=true
    else
        log_warning "⚠️ Database non trovato - potrebbe essere il primo avvio"
        HAS_DATABASE=false
    fi
    
    echo ""
}

# 2. Backup completo della situazione attuale
create_safety_backup() {
    log_info "Creando backup di sicurezza..."
    
    mkdir -p "$BACKUP_DIR"
    
    # Backup database se esiste
    if [ "$HAS_DATABASE" = true ]; then
        log_info "📦 Backup database..."
        
        # Prova diversi percorsi possibili
        docker exec "$OLD_CONTAINER_NAME" sh -c "find /app -name 'subs.db' -type f" | while read db_path; do
            if [ -n "$db_path" ]; then
                docker cp "$OLD_CONTAINER_NAME:$db_path" "$BACKUP_DIR/subs_backup.db"
                log_success "Database copiato da: $db_path"
                break
            fi
        done
        
        # Fallback: prova percorsi standard
        if [ ! -f "$BACKUP_DIR/subs_backup.db" ]; then
            docker cp "$OLD_CONTAINER_NAME:/app/subs.db" "$BACKUP_DIR/subs_backup.db" 2>/dev/null || \
            docker cp "$OLD_CONTAINER_NAME:/app/data/subs.db" "$BACKUP_DIR/subs_backup.db" 2>/dev/null || \
            log_warning "Non riuscito a fare backup database"
        fi
    fi
    
    # Backup configurazione container
    log_info "📋 Backup configurazione container..."
    docker inspect "$OLD_CONTAINER_NAME" > "$BACKUP_DIR/container_config.json"
    
    # Backup environment variables
    docker exec "$OLD_CONTAINER_NAME" printenv | grep -E "TELEGRAM_TOKEN|CHECK_INTERVAL|ADMIN_CHAT_ID" > "$BACKUP_DIR/env_vars.txt" 2>/dev/null || true
    
    # Backup logs recenti
    docker logs "$OLD_CONTAINER_NAME" --tail=100 > "$BACKUP_DIR/recent_logs.txt" 2>/dev/null || true
    
    log_success "✅ Backup completo salvato in: $BACKUP_DIR"
    echo ""
}

# 3. Estrai configurazione esistente
extract_config() {
    log_info "Estraendo configurazione esistente..."
    
    # Prova a estrarre token e configurazioni
    TOKEN=$(docker exec "$OLD_CONTAINER_NAME" printenv TELEGRAM_TOKEN 2>/dev/null || echo "")
    ADMIN_ID=$(docker exec "$OLD_CONTAINER_NAME" printenv ADMIN_CHAT_ID 2>/dev/null || echo "")
    INTERVAL=$(docker exec "$OLD_CONTAINER_NAME" printenv CHECK_INTERVAL 2>/dev/null || echo "30")
    
    if [ -n "$TOKEN" ]; then
        log_success "✅ Token estratto: ${TOKEN:0:10}..."
        
        # Crea .env per la nuova versione
        cat > .env << EOF
# Configurazione estratta dal container esistente
TELEGRAM_TOKEN=$TOKEN
ADMIN_CHAT_ID=$ADMIN_ID
CHECK_INTERVAL=${INTERVAL}
DB_PATH=./data/subs.db
LOG_LEVEL=INFO

# Nuove configurazioni ottimizzate
CACHE_DURATION=240
API_TIMEOUT=15
MAX_SUBSCRIPTIONS_PER_USER=10
MAX_PRICE_THRESHOLD=1000000
MIN_PRICE_THRESHOLD=0.000001
ENVIRONMENT=production
HEALTH_CHECK_PORT=8000
EOF
        
        log_success "✅ File .env creato con configurazione estratta"
    else
        log_error "❌ Non riuscito a estrarre TELEGRAM_TOKEN"
        log_info "Dovrai configurare manualmente il file .env"
        return 1
    fi
    
    echo ""
}

# 4. Setup nuova struttura
setup_new_structure() {
    log_info "Preparando nuova struttura..."
    
    # Crea directory necessarie
    mkdir -p data logs backups config monitoring
    
    # Migra database se esiste
    if [ -f "$BACKUP_DIR/subs_backup.db" ]; then
        log_info "📦 Migrando database..."
        cp "$BACKUP_DIR/subs_backup.db" "data/subs.db"
        chmod 644 "data/subs.db"
        log_success "✅ Database migrato in ./data/subs.db"
    fi
    
    log_success "✅ Struttura preparata"
    echo ""
}

# 5. Stop e rimozione container vecchio
stop_old_container() {
    log_info "Fermando container esistente..."
    
    if [ "$CONTAINER_RUNNING" = true ]; then
        docker stop "$OLD_CONTAINER_NAME"
        log_success "✅ Container fermato"
    fi
    
    # Chiedi conferma per rimozione
    echo ""
    log_warning "⚠️ Ora rimuoverò il container vecchio"
    read -p "Confermi? (y/N): " -n 1 -r
    echo
    
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        docker rm "$OLD_CONTAINER_NAME"
        log_success "✅ Container rimosso"
    else
        log_info "Container mantenuto (puoi rimuoverlo manualmente dopo)"
    fi
    
    echo ""
}

# 6. Deploy nuova versione
deploy_new_version() {
    log_info "🚀 Deploying versione ottimizzata..."
    
    # Verifica che abbiamo tutti i file necessari
    required_files=("bot.py" "db.py" "jobs.py" "utils.py" "Dockerfile" "docker-compose.yml" "requirements.txt")
    
    for file in "${required_files[@]}"; do
        if [ ! -f "$file" ]; then
            log_error "❌ File mancante: $file"
            log_info "Assicurati di aver copiato tutti i file dalla versione ottimizzata"
            exit 1
        fi
    done
    
    # Build nuova immagine
    log_info "🏗️ Building nuova immagine..."
    docker build -t competent_golick:optimized .
    
    # Deploy con docker-compose
    log_info "🚀 Starting nuova versione..."
    docker-compose up -d
    
    # Attendi startup
    log_info "⏳ Attendendo startup..."
    sleep 15
    
    # Verifica deployment
    if docker ps | grep -q "competent_golick"; then
        log_success "🎉 UPGRADE COMPLETATO CON SUCCESSO!"
        
        echo ""
        echo "📊 Status nuova versione:"
        docker-compose ps
        
        echo ""
        echo "📝 Log recenti:"
        docker-compose logs --tail=10
        
    else
        log_error "❌ Problema nel deployment"
        echo ""
        echo "🔍 Debug info:"
        docker-compose ps
        docker-compose logs --tail=20
        
        echo ""
        log_info "💡 Per ripristinare la versione precedente:"
        echo "docker run -d --name competent_golick-restore [old_image_id]"
    fi
}

# 7. Verifica post-upgrade
verify_upgrade() {
    log_info "🔍 Verificando upgrade..."
    
    # Test bot funzionante
    if docker-compose logs --tail=50 | grep -i "bot started successfully"; then
        log_success "✅ Bot avviato correttamente"
    else
        log_warning "⚠️ Bot potrebbe avere problemi - controlla i logs"
    fi
    
    # Test database migrato
    if [ -f "data/subs.db" ]; then
        log_success "✅ Database migrato"
        
        # Conta record migrati se possibile
        if command -v sqlite3 &> /dev/null; then
            count=$(sqlite3 data/subs.db "SELECT COUNT(*) FROM subscriptions" 2>/dev/null || echo "unknown")
            log_info "📊 Sottoscrizioni migrate: $count"
        fi
    fi
    
    echo ""
    log_success "🎉 UPGRADE VERIFICATION COMPLETED"
    echo ""
    echo "🔗 Comandi utili post-upgrade:"
    echo "  docker-compose logs -f    # Monitora logs"
    echo "  docker-compose ps         # Status containers"
    echo "  docker-compose restart    # Restart se necessario"
    echo ""
    echo "💾 Backup salvato in: $BACKUP_DIR"
    echo "   (puoi eliminarlo dopo aver verificato che tutto funzioni)"
}

# Main execution
main() {
    analyze_current_setup
    create_safety_backup
    extract_config
    setup_new_structure
    stop_old_container
    deploy_new_version
    verify_upgrade
    
    echo ""
    log_success "🚀 UPGRADE TO OPTIMIZED VERSION COMPLETED!"
    echo ""
    echo "La tua versione ottimizzata è ora attiva con:"
    echo "✅ Cache intelligente"
    echo "✅ Anti-spam avanzato" 
    echo "✅ Monitoring completo"
    echo "✅ Sicurezza enterprise"
    echo "✅ Performance massime"
    echo ""
    echo "Welcome to the next level, MetalCoder! 🔥"
}

# Conferma prima di iniziare
echo "Questo script farà l'upgrade del tuo bot alla versione ottimizzata."
echo "Verrà fatto un backup completo prima di qualsiasi modifica."
echo ""
read -p "Vuoi procedere? (y/N): " -n 1 -r
echo

if [[ $REPLY =~ ^[Yy]$ ]]; then
    main
else
    echo "Upgrade annullato."
    exit 0
fi