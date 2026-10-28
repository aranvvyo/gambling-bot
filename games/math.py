from decimal import Decimal, ROUND_DOWN
import hashlib
from services.fairness import unit_float


def dice_probability(direction: str, target: int) -> Decimal:
    direction = direction.lower()
    if not 1 <= target <= 99 or direction not in {'under', 'over'}:
        raise ValueError('target must be 1..99 and direction under/over')
    if direction == 'over' and target == 99:
        raise ValueError('over 99 has zero win probability')
    wins = target if direction == 'under' else 99-target
    return Decimal(wins) / Decimal(100)


def dice_result(digest: str, direction: str, target: int, edge: Decimal = Decimal('0.01')):
    if len(digest) < 4: raise ValueError('digest is too short')
    limit=(1<<256)-((1<<256)%100); counter=0
    while True:
        raw=hashlib.sha256(f'{digest}:dice:{counter}'.encode()).digest(); n=int.from_bytes(raw,'big')
        if n<limit: roll=n%100; break
        counter+=1
    probability = dice_probability(direction, target)
    won = roll < target if direction == 'under' else roll > target
    multiplier = ((Decimal(1)-edge) / probability).quantize(Decimal('0.01'), rounding=ROUND_DOWN)
    return roll, won, multiplier, probability


def chicken_safe_tile(digest: str, step: int, tiles: int = 3) -> int:
    if tiles < 2 or not 0 <= step < 100: raise ValueError('invalid Chicken Road settings')
    from services.fairness import derive_int
    return derive_int(digest, f'step:{step}', tiles)


def chicken_multiplier(steps: int, tiles: int = 3, edge: Decimal = Decimal('0.01')) -> Decimal:
    if steps < 0 or tiles < 2 or not Decimal(0) <= edge < Decimal(1): raise ValueError('invalid Chicken Road settings')
    return ((Decimal(tiles) ** steps) * (Decimal(1)-edge)).quantize(Decimal('0.01'), rounding=ROUND_DOWN)


def pump_crash_point(digest: str, edge: Decimal = Decimal('0.01'), cap: Decimal = Decimal('100')) -> Decimal:
    """Inverse-CDF crash point: P(crash >= x)=(1-edge)/x, capped at 100x."""
    u = Decimal(int(digest[:13], 16)) / Decimal(16**13)
    point = (Decimal(1)-edge) / max(Decimal('0.0000000000001'), Decimal(1)-u)
    return max(Decimal('1.00'), min(cap, point)).quantize(Decimal('0.01'), rounding=ROUND_DOWN)


def pump_multiplier(elapsed_seconds: float) -> Decimal:
    if elapsed_seconds < 0: raise ValueError('elapsed time cannot be negative')
    return (Decimal('1.00') + Decimal(str(elapsed_seconds)) * Decimal('0.08')).quantize(Decimal('0.01'), rounding=ROUND_DOWN)
