#!/bin/bash

# 🚀 Crypto Alert Bot - Deploy Script
# Developed by MetalCoder

set -euo pipefail

# Configurazione
BOT_NAME="crypto-alert-bot"
DOCKER_IMAGE="metalcoder/crypto-alert-bot"
VERSION="${1:-latest}"
ENV_FILE=".env"

# Colori per output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Funzioni utility
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Verifica prerequisiti
check_prerequisites() {
    log_info "Verificando prerequisiti..."
    
    # Verifica Docker
    if ! command -v docker &> /dev/null; then
        log_error "Docker non è installato"
        exit 1
    fi
    
    # Verifica Docker Compose
    if ! command -v docker-compose &> /dev/null; then
        log_error "Docker Compose non è installato"
        exit 1
    fi
    
    # Verifica file .env
    if [[ ! -f "$ENV_FILE" ]]; then
        log_error "File .env mancante"
        create_env_template
        exit 1
    fi
    
    # Verifica token Telegram
    if ! grep -q "TELEGRAM_TOKEN=" "$ENV_FILE"; then
        log_error "TELEGRAM_TOKEN mancante in .env"
        exit 1
    fi
    
    log_success "Prerequisiti verificati"
}

# Crea template .env
create_env_template() {
    log_info "Creando template .env..."
    
    cat > "$ENV_FILE" << 'EOF'
# Telegram Bot Configuration
TELEGRAM_TOKEN=your_telegram_bot_token_here
ADMIN_CHAT_ID=your_telegram_chat_id_here

# Bot Settings
CHECK_INTERVAL=300
LOG_LEVEL=INFO

# Database
DB_PATH=./data/subs.db

# Optional: Monitoring
PROMETHEUS_ENABLED=false
BACKUP_ENABLED=false
EOF
    
    log_warning "Template .env creato. Compila i valori richiesti!"
}

# Crea directory necessarie
setup_directories() {
    log_info "Creando directory necessarie..."
    
    mkdir -p data logs backups config monitoring
    
    # Imposta permessi corretti
    chmod 755 data logs backups
    
    log_success "Directory create"
}

# Build dell'immagine Docker
build_image() {
    log_info "Building Docker image..."
    
    docker build \
        --tag "$DOCKER_IMAGE:$VERSION" \
        --tag "$DOCKER_IMAGE:latest" \
        --build-arg VERSION="$VERSION" \
        .
    
    log_success "Immagine Docker buildada: $DOCKER_IMAGE:$VERSION"
}

# Deploy del bot
deploy_bot() {
    log_info "Deploying bot..."
    
    # Stop container esistente se presente
    if docker ps -q -f name="$BOT_NAME" | grep -q .; then
        log_info "Stopping existing container..."
        docker-compose down
    fi
    
    # Backup database se esistente
    if [[ -f "data/subs.db" ]]; then
        backup_file="backups/subs_$(date +%Y%m%d_%H%M%S).db"
        cp "data/subs.db" "$backup_file"
        log_info "Database backed up to $backup_file"
    fi
    
    # Start nuovo container
    docker-compose up -d
    
    log_success "Bot deployed successfully"
}

# Verifica deployment
verify_deployment() {
    log_info "Verificando deployment..."
    
    # Attendi startup
    sleep 10
    
    # Verifica container
    if ! docker ps | grep -q "$BOT_NAME"; then
        log_error "Container non è in running"
        docker-compose logs --tail=20
        exit 1
    fi
    
    # Verifica logs per errori
    if docker-compose logs --tail=50 | grep -i error; then
        log_warning "Trovati errori nei logs"
    fi
    
    log_success "Deployment verificato"
}

# Mostra status
show_status() {
    log_info "Status del bot:"
    
    echo ""
    echo "🐳 Container Status:"
    docker ps --filter name="$BOT_NAME" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
    
    echo ""
    echo "📊 Resource Usage:"
    docker stats "$BOT_NAME" --no-stream --format "table {{.Container}}\t{{.CPUPerc}}\t{{.MemUsage}}"
    
    echo ""
    echo "📝 Recent Logs:"
    docker-compose logs --tail=10
}

# Comandi disponibili
show_help() {
    echo "🤖 Crypto Alert Bot - Deploy Script"
    echo ""
    echo "Usage: $0 [COMMAND] [VERSION]"
    echo ""
    echo "Commands:"
    echo "  deploy [version]  - Deploy bot (default: latest)"
    echo "  build [version]   - Build Docker image"
    echo "  start            - Start bot container"
    echo "  stop             - Stop bot container"
    echo "  restart          - Restart bot container"
    echo "  logs             - Show bot logs"
    echo "  status           - Show bot status"
    echo "  update           - Update to latest version"
    echo "  backup           - Create database backup"
    echo "  help             - Show this help"
    echo ""
    echo "Examples:"
    echo "  $0 deploy         # Deploy latest version"
    echo "  $0 deploy v1.2.0  # Deploy specific version"
    echo "  $0 logs           # Show recent logs"
}

# Backup manuale database
backup_database() {
    log_info "Creating database backup..."
    
    if [[ ! -f "data/subs.db" ]]; then
        log_warning "Database file not found"
        return
    fi
    
    backup_file="backups/manual_backup_$(date +%Y%m%d_%H%M%S).db"
    cp "data/subs.db" "$backup_file"
    
    log_success "Database backed up to $backup_file"
}

# Update bot
update_bot() {
    log_info "Updating bot to latest version..."
    
    # Pull latest changes (se usando git)
    if [[ -d ".git" ]]; then
        git pull origin main
    fi
    
    # Rebuild e redeploy
    build_image
    deploy_bot
    verify_deployment
    
    log_success "Bot updated successfully"
}

# Main script
main() {
    case "${1:-deploy}" in
        "deploy")
            check_prerequisites
            setup_directories
            build_image
            deploy_bot
            verify_deployment
            show_status
            ;;
        "build")
            build_image
            ;;
        "start")
            docker-compose up -d
            log_success "Bot started"
            ;;
        "stop")
            docker-compose down
            log_success "Bot stopped"
            ;;
        "restart")
            docker-compose restart
            log_success "Bot restarted"
            ;;
        "logs")
            docker-compose logs -f
            ;;
        "status")
            show_status
            ;;
        "update")
            update_bot
            ;;
        "backup")
            backup_database
            ;;
        "help"|"-h"|"--help")
            show_help
            ;;
        *)
            log_error "Comando non riconosciuto: $1"
            show_help
            exit 1
            ;;
    esac
}

# Esegui main con tutti i parametri
main "$@"