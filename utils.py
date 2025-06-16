import re
import logging
from typing import Optional, Dict

logger = logging.getLogger(__name__)

# Mapping asset user-friendly -> CoinGecko ID
SUPPORTED_ASSETS: Dict[str, str] = {
    # Major cryptocurrencies
    "btc": "bitcoin",
    "bitcoin": "bitcoin",
    
    "eth": "ethereum", 
    "ethereum": "ethereum",
    
    "ada": "cardano",
    "cardano": "cardano",
    
    "sol": "solana",
    "solana": "solana",
    
    "dot": "polkadot",
    "polkadot": "polkadot",
    
    "matic": "matic-network",
    "polygon": "matic-network",
    
    "link": "chainlink",
    "chainlink": "chainlink",
    
    "avax": "avalanche-2",
    "avalanche": "avalanche-2",
    
    "atom": "cosmos",
    "cosmos": "cosmos",
    
    "xtz": "tezos",
    "tezos": "tezos",
    
    "algo": "algorand",
    "algorand": "algorand",
    
    "near": "near",
    
    "ftm": "fantom",
    "fantom": "fantom",
    
    "one": "harmony",
    "harmony": "harmony",
    
    # Stablecoins (per completezza)
    "usdt": "tether",
    "usdc": "usd-coin",
    "busd": "binance-usd",
    
    # Altri popolari
    "bnb": "binancecoin",
    "binance": "binancecoin",
    
    "xrp": "ripple",
    "ripple": "ripple",
    
    "doge": "dogecoin",
    "dogecoin": "dogecoin",
}

def validate_asset(user_input: str) -> Optional[str]:
    """
    Valida e normalizza input asset dell'utente
    
    Args:
        user_input: Input utente (es. "btc", "Bitcoin", "BTC")
        
    Returns:
        CoinGecko ID se valido, None altrimenti
    """
    if not user_input or not isinstance(user_input, str):
        return None
        
    # Normalizza input
    normalized = user_input.lower().strip()
    
    # Rimuovi spazi e caratteri speciali
    normalized = re.sub(r'[^a-z0-9-]', '', normalized)
    
    if not normalized:
        return None
    
    # Cerca match esatto
    if normalized in SUPPORTED_ASSETS:
        asset_id = SUPPORTED_ASSETS[normalized]
        logger.debug(f"Asset validation: '{user_input}' -> '{asset_id}'")
        return asset_id
    
    # Cerca match parziale (per casi come "bitcoin" vs "btc")
    for key, value in SUPPORTED_ASSETS.items():
        if normalized in key or key in normalized:
            logger.debug(f"Asset partial match: '{user_input}' -> '{value}' (via '{key}')")
            return value
    
    logger.debug(f"Asset validation failed: '{user_input}' not supported")
    return None

def format_price(price: float) -> str:
    """
    Formatta prezzo per display elegante
    
    Args:
        price: Prezzo in USD
        
    Returns:
        Stringa formattata (es. "$1,234.56", "$1.23M")
    """
    if price >= 1_000_000:
        return f"${price/1_000_000:.2f}M"
    elif price >= 1_000:
        return f"${price:,.2f}"
    elif price >= 1:
        return f"${price:.2f}"
    elif price >= 0.01:
        return f"${price:.3f}"
    elif price >= 0.001:
        return f"${price:.4f}"
    else:
        return f"${price:.6f}"

def format_percentage(value: float) -> str:
    """
    Formatta percentuale con colore emoji
    
    Args:
        value: Valore percentuale
        
    Returns:
        Stringa formattata con emoji
    """
    if value >= 10:
        return f"🚀 +{value:.1f}%"
    elif value >= 5:
        return f"📈 +{value:.1f}%"
    elif value >= 0:
        return f"⬆️ +{value:.1f}%"
    elif value >= -5:
        return f"⬇️ {value:.1f}%"
    elif value >= -10:
        return f"📉 {value:.1f}%"
    else:
        return f"💥 {value:.1f}%"

def validate_threshold(threshold: float) -> tuple[bool, str]:
    """
    Valida soglia prezzo
    
    Args:
        threshold: Soglia inserita dall'utente
        
    Returns:
        (is_valid, error_message)
    """
    if threshold <= 0:
        return False, "La soglia deve essere maggiore di 0"
    
    if threshold > 1_000_000:
        return False, "Soglia troppo alta (massimo $1,000,000)"
    
    if threshold < 0.000001:
        return False, "Soglia troppo bassa (minimo $0.000001)"
    
    return True, ""

def get_asset_display_name(asset_id: str) -> str:
    """
    Converte CoinGecko ID in nome display
    
    Args:
        asset_id: ID CoinGecko
        
    Returns:
        Nome display user-friendly
    """
    # Reverse lookup nel mapping
    for user_name, coingecko_id in SUPPORTED_ASSETS.items():
        if coingecko_id == asset_id:
            # Preferisci simboli corti
            if len(user_name) <= 4 and user_name.isalpha():
                return user_name.upper()
    
    # Fallback: capitalizza e sostituisci trattini
    return asset_id.replace('-', ' ').title()

def get_supported_assets_list() -> str:
    """
    Genera lista formattata degli asset supportati
    
    Returns:
        Stringa con lista asset
    """
    # Raggruppa per simboli principali
    main_symbols = []
    for symbol, asset_id in SUPPORTED_ASSETS.items():
        # Prendi solo simboli corti e unici
        if len(symbol) <= 4 and symbol.isalpha():
            if asset_id not in [SUPPORTED_ASSETS.get(existing) for existing in main_symbols]:
                main_symbols.append(symbol.upper())
    
    # Ordina e raggruppa
    main_symbols.sort()
    return ", ".join(main_symbols)

def sanitize_user_input(text: str, max_length: int = 100) -> str:
    """
    Sanitizza input utente per sicurezza
    
    Args:
        text: Testo da sanitizzare
        max_length: Lunghezza massima
        
    Returns:
        Testo sanitizzato
    """
    if not text:
        return ""
    
    # Rimuovi caratteri di controllo
    sanitized = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', text)
    
    # Limita lunghezza
    sanitized = sanitized[:max_length]
    
    # Trim spazi
    sanitized = sanitized.strip()
    
    return sanitized

def parse_price_input(user_input: str) -> Optional[float]:
    """
    Parsa input prezzo dall'utente con formati flessibili
    
    Args:
        user_input: Input utente (es. "50k", "$1,234.56", "1.5M")
        
    Returns:
        Prezzo come float o None se invalido
    """
    if not user_input:
        return None
    
    # Rimuovi spazi e simboli comuni
    cleaned = re.sub(r'[$,\s]', '', user_input.lower())
    
    # Gestisci suffissi
    multiplier = 1
    if cleaned.endswith('k'):
        multiplier = 1_000
        cleaned = cleaned[:-1]
    elif cleaned.endswith('m'):
        multiplier = 1_000_000
        cleaned = cleaned[:-1]
    elif cleaned.endswith('b'):
        multiplier = 1_000_000_000
        cleaned = cleaned[:-1]
    
    try:
        price = float(cleaned) * multiplier
        return price if price > 0 else None
    except ValueError:
        return None

def is_admin(chat_id: int) -> bool:
    """
    Verifica se utente è admin
    
    Args:
        chat_id: ID chat Telegram
        
    Returns:
        True se admin
    """
    import os
    admin_id = os.getenv("ADMIN_CHAT_ID")
    return admin_id and str(chat_id) == admin_id

def get_time_until_next_check(interval_seconds: int) -> str:
    """
    Calcola tempo al prossimo controllo
    
    Args:
        interval_seconds: Intervallo in secondi
        
    Returns:
        Stringa tempo rimanente
    """
    from datetime import datetime, timedelta
    
    # Stima prossimo check (semplificata)
    next_check = datetime.now() + timedelta(seconds=interval_seconds)
    minutes = interval_seconds // 60
    
    if minutes < 60:
        return f"{minutes} minuti"
    else:
        hours = minutes // 60
        remaining_minutes = minutes % 60
        if remaining_minutes == 0:
            return f"{hours} ore"
        else:
            return f"{hours}h {remaining_minutes}m"

def truncate_text(text: str, max_length: int = 200, suffix: str = "...") -> str:
    """
    Tronca testo mantenendo leggibilità
    
    Args:
        text: Testo da troncare
        max_length: Lunghezza massima
        suffix: Suffisso per testo troncato
        
    Returns:
        Testo troncato
    """
    if len(text) <= max_length:
        return text
    
    # Tronca a parola intera se possibile
    truncated = text[:max_length - len(suffix)]
    last_space = truncated.rfind(' ')
    
    if last_space > max_length * 0.8:  # Se lo spazio è abbastanza vicino
        truncated = truncated[:last_space]
    
    return truncated + suffix