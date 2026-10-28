import secrets
from decimal import Decimal, ROUND_DOWN

_rng = secrets.SystemRandom()

def mines_multiplier(mines: int, revealed: int, edge: Decimal = Decimal("0.01"), board_size: int = 25) -> Decimal:
    if board_size < 2 or not 1 <= mines < board_size or not 0 <= revealed <= board_size-mines:
        raise ValueError("invalid mines/revealed")
    # Fair odds: total combinations / safe-path combinations, adjusted by house edge.
    odds = Decimal(1)
    for i in range(revealed):
        odds *= Decimal(board_size-i) / Decimal(board_size-mines-i)
    return (odds * (Decimal(1)-edge)).quantize(Decimal("0.01"), rounding=ROUND_DOWN)

def tower_multiplier(floors: int, choices: int, edge: Decimal=Decimal("0.01")) -> Decimal:
    if floors < 1 or choices not in (2,3): raise ValueError("invalid tower settings")
    return ((Decimal(choices)**floors)*(Decimal(1)-edge)).quantize(Decimal("0.01"), rounding=ROUND_DOWN)

def limbo_multiplier(target: Decimal, edge: Decimal=Decimal("0.01")) -> Decimal:
    if target < 1.01 or target > 1000: raise ValueError("target must be 1.01..1000")
    return (target*(Decimal(1)-edge)).quantize(Decimal("0.01"),rounding=ROUND_DOWN)

def limbo_roll(target: Decimal, edge: Decimal=Decimal("0.01")) -> Decimal:
    # The fractional uniform is sampled with cryptographic randomness.
    # P(result >= target) ~= 1/target; target*(1-edge) return creates the configured edge.
    u = Decimal(secrets.randbelow(10**12)+1) / Decimal(10**12+1)
    return (Decimal(1)/u).quantize(Decimal("0.01"))

def crash_point(edge: Decimal=Decimal("0.01")) -> Decimal:
    # Inverse-CDF model: P(crash >= x) ~= (1-edge)/x for x >= 1.
    # Rounded down to cents and capped to keep outcomes/payouts bounded.
    n = secrets.randbits(52)
    u = Decimal(n) / Decimal(2**52)
    denominator = Decimal(1) - u
    point = (Decimal(1)-edge) / denominator
    return max(Decimal("1.00"), min(point, Decimal(1000))).quantize(Decimal("0.01"), rounding=ROUND_DOWN)

def blackjack_value(cards):
    total = sum(min(c,10) if c != 1 else 11 for c in cards)
    aces = sum(c == 1 for c in cards)
    while total > 21 and aces:
        total -= 10; aces -= 1
    return total

def deck(result_digest=None):
    if result_digest is not None:
        from services.fairness import derive_deck
        return derive_deck(result_digest)
    cards = [rank for _ in range(4) for rank in range(1,14)]
    _rng.shuffle(cards)
    return cards

def payout(bet: int, multiplier: Decimal, cap: int) -> int:
    if bet <= 0 or cap < 0 or multiplier < 0: raise ValueError("invalid payout inputs")
    return min(cap, int((Decimal(bet)*multiplier).to_integral_value(rounding=ROUND_DOWN)))

def safe_index(size: int) -> int:
    return secrets.randbelow(size)


def limo_multiplier(cars: int, edge: Decimal=Decimal("0.01")) -> Decimal:
    if not 2 <= cars <= 5 or not Decimal(0) <= edge < Decimal(1): raise ValueError("invalid limousine game settings")
    return (Decimal(cars)*(Decimal(1)-edge)).quantize(Decimal("0.01"),rounding=ROUND_DOWN)

def blackjack_return(bet: int, player: int, dealer: int, natural: bool=False, dealer_natural: bool=False, cap: int=1_000_000) -> int:
    if bet <= 0 or player < 0 or dealer < 0: raise ValueError("invalid blackjack settlement")
    if player > 21: return 0
    if natural and not dealer_natural: return payout(bet,Decimal("2.5"),cap)
    if player == dealer: return bet
    if dealer > 21 or player > dealer: return payout(bet,Decimal(2),cap)
    return 0
