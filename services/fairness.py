"""Durable commitments and deterministic, independently checkable game inputs."""
import hashlib
import hmac
import json
import secrets
from decimal import Decimal, ROUND_DOWN


def commitment(server_seed: str) -> str:
    return hashlib.sha256(server_seed.encode()).hexdigest()


def digest(server_seed: str, client_seed: str, nonce: int, game: str) -> str:
    message = f'{client_seed}:{nonce}:{game}'.encode()
    return hmac.new(server_seed.encode(), message, hashlib.sha256).hexdigest()


def unit_float(result_digest: str) -> float:
    return int(result_digest[:13], 16) / float(16**13)


def derive_int(result_digest: str, label: str, upper: int) -> int:
    if upper < 1 or len(result_digest) != 64:
        raise ValueError('invalid fair derivation inputs')
    limit = (1 << 256) - ((1 << 256) % upper)
    counter = 0
    while True:
        block = hashlib.sha256(f'{result_digest}:{label}:{counter}'.encode()).digest()
        value = int.from_bytes(block, 'big')
        if value < limit: return value % upper
        counter += 1


def mines_layout(result_digest: str, tiles: int, mines: int) -> list[int]:
    if not 1 <= mines < tiles: raise ValueError('invalid mines settings')
    ranked = sorted((hashlib.sha256(f'{result_digest}:mine:{i}'.encode()).digest(), i) for i in range(tiles))
    return sorted(i for _, i in ranked[:mines])


def safe_path(result_digest: str, steps: int, choices: int) -> list[int]:
    return [derive_int(result_digest, f'safe:{i}', choices) for i in range(steps)]


def crash_point(result_digest: str, edge: float = .01) -> str:
    u = Decimal(int(result_digest[:13], 16)) / Decimal(16**13)
    point = max(Decimal('1.00'), min((Decimal(1)-Decimal(str(edge))) / (Decimal(1)-u), Decimal('1000')))
    return str(point.quantize(Decimal('.01'), rounding=ROUND_DOWN))


def derive_deck(result_digest: str) -> list[int]:
    cards = [rank for _ in range(4) for rank in range(1, 14)]
    for i in range(len(cards)-1, 0, -1):
        j = derive_int(result_digest, f'deck:{i}', i+1)
        cards[i], cards[j] = cards[j], cards[i]
    return cards


def verify_game_outcome(game: str, result_digest: str, outcome: str) -> bool:
    if outcome in ('refunded after restart', 'refunded before play', 'refunded after engine error'): return True
    try:
        r = json.loads(outcome)
        if r.get('algorithm') != 'casino-v1': return False
        if game == 'mines':
            from services.game_math import mines_multiplier, payout
            layout = mines_layout(result_digest, r['tiles'], r['mines'])
            opened = r['opened']; safe_count = sum(i not in layout for i in opened)
            hit = r.get('title') == '💥 Mine hit'
            if layout != r['layout'] or len(set(opened)) != len(opened) or any(i not in range(r['tiles']) for i in opened) or (any(i in layout for i in opened) != hit): return False
            expected = 0 if hit or r.get('title') == 'timeout' else payout(r['bet'], mines_multiplier(r['mines'], safe_count, Decimal(str(r['edge'])), r['tiles']), r['cap'])
            return expected == r['payout']
        if game == 'dragon_tower':
            from services.game_math import tower_multiplier, payout
            path = safe_path(result_digest, r['steps_total'], r['choices'])
            if path != r['safe_path'] or not 0 <= r['steps'] <= r['steps_total']: return False
            chosen = r['chosen_path']
            if len(chosen) not in (r['steps'], r['steps']+1) or chosen[:r['steps']] != path[:r['steps']]: return False
            lost = r.get('title') == '🐉 The tower claimed your bet.'
            if lost and (len(chosen) != r['steps']+1 or chosen[-1] == path[r['steps']]): return False
            if not lost and len(chosen) != r['steps']: return False
            expected = 0 if r.get('title') in ('🐉 The tower claimed your bet.','timeout') else (payout(r['bet'], tower_multiplier(r['steps'], r['choices'], Decimal(str(r['edge']))), r['cap']) if r['steps'] else 0)
            return expected == r['payout']
        if game == 'chicken-road':
            from games.math import chicken_safe_tile, chicken_multiplier
            from services.game_math import payout
            path = [chicken_safe_tile(result_digest, i) for i in range(r['steps_total'])]
            if path != r['safe_path'] or not 0 <= r['steps'] <= r['steps_total']: return False
            chosen = r['chosen_path']
            if len(chosen) not in (r['steps'], r['steps']+1) or chosen[:r['steps']] != path[:r['steps']]: return False
            lost = r.get('title') == '🐉 The tower claimed your bet.'
            if lost and (len(chosen) != r['steps']+1 or chosen[-1] == path[r['steps']]): return False
            if not lost and len(chosen) != r['steps']: return False
            expected = 0 if r.get('reason','').startswith(('Wrong tile','expired')) else (payout(r['bet'], chicken_multiplier(r['steps'], edge=Decimal(str(r['edge']))), r['cap']) if r['steps'] else 0)
            return expected == r['payout']
        if game == 'limo':
            from services.game_math import limo_multiplier, payout
            won = derive_int(result_digest, 'limo-car', r['cars']) == r['winner']
            expected = payout(r['bet'], limo_multiplier(r['cars'], Decimal(str(r['edge']))), r['cap']) if won and r.get('chosen') == r['winner'] else 0
            return won and expected == r['payout']
        if game == 'limbo':
            from services.game_math import payout
            u = Decimal(int(result_digest[:13], 16)) / Decimal(16**13)
            expected = (Decimal(1) / max(u, Decimal(1)/Decimal(16**13))).quantize(Decimal('.01'), rounding=ROUND_DOWN)
            won = expected >= Decimal(str(r['target']))
            amount = payout(r['bet'], Decimal(str(r['target']))*(1-Decimal(str(r['edge']))), r['cap']) if won else 0
            return expected == Decimal(str(r['roll'])) and won == r['won'] and amount == r['payout']
        if game == 'crash':
            from services.game_math import payout
            point = crash_point(result_digest, float(r['edge']))
            mult = Decimal(str(r['multiplier'])) if r.get('multiplier') else None
            amount = payout(r['bet'], mult, r['cap']) if r.get('reason') == 'cashout' and mult is not None and mult < Decimal(point) else (0 if r.get('reason') in ('crash','timeout') else -1)
            return point == str(r['point']) and amount == r['payout']
        if game == 'blackjack':
            from services.game_math import blackjack_value, blackjack_return
            dealt = r['dealt']; deck = derive_deck(result_digest)
            if len(dealt) < 4 or dealt != deck[:len(dealt)]: return False
            player, dealer = r['player'], r['dealer']
            if len(dealt) < 4: return False
            player_draws = player[2:]; dealer_draws = dealer[2:]
            if player[:2] != dealt[:2] or dealer[:2] != dealt[2:4]: return False
            if dealt[4:4+len(player_draws)] != player_draws or dealt[4+len(player_draws):] != dealer_draws: return False
            reason = r.get('reason', 'settled')
            if reason == 'timeout': return not dealer_draws and r['payout'] == 0
            player_total, dealer_total = blackjack_value(player), blackjack_value(dealer)
            natural = len(player)==2 and player_total==21
            dealer_natural = len(dealer)==2 and dealer_total==21
            if reason == 'bust':
                if player_total <= 21 or dealer_draws or r['payout'] != 0: return False
            elif reason == 'stand':
                if player_total > 21: return False
                next_card = 4 + len(player_draws)
                expected_dealer = list(dealt[2:4])
                while blackjack_value(expected_dealer) < 17:
                    if next_card >= len(deck): return False
                    expected_dealer.append(deck[next_card]); next_card += 1
                if expected_dealer != dealer or next_card != len(dealt): return False
            elif reason == 'settled':
                if len(dealt) != 4 or not (natural or dealer_natural): return False
            else: return False
            expected = blackjack_return(r['bet'], player_total, dealer_total, natural, dealer_natural, r['cap'])
            return expected == r['payout']
        if game == 'dice':
            from games.math import dice_result
            roll, won, multiplier, _ = dice_result(result_digest, r['direction'], int(r['target']), Decimal(str(r['edge'])))
            from services.game_math import payout
            expected_pay = payout(r['bet'], multiplier, r['cap']) if won else 0
            return roll == r['roll'] and won == r['won'] and expected_pay == r['payout']
        if game == 'pump':
            from games.math import pump_crash_point
            from services.game_math import payout
            point = pump_crash_point(result_digest, Decimal(str(r['edge'])), Decimal(str(r['cap'])))
            if str(point) != str(r['point']): return False
            if r.get('reason','').startswith('Pump burst'): return r['payout'] == 0 and Decimal(str(r.get('attempted','0'))) >= point and Decimal(str(r.get('multiplier','1.00'))) + Decimal('.25') == Decimal(str(r.get('attempted','0')))
            if r.get('reason','').startswith('expired'): return r['payout'] == 0
            # A successful cash-out can only be at a 0.25x step strictly below burst.
            mult = Decimal(str(r.get('multiplier', '1.00')))
            return mult < point and mult >= 1 and mult % Decimal('.25') == 0 and payout(r['bet'], mult, int(r['cap'])) == r['payout']
        return False
    except Exception:
        return False


class FairnessService:
    def __init__(self, db, rotation_seconds=1800, publish=None, publish_reveal=None):
        if rotation_seconds < 60: raise ValueError('rotation interval must be at least 60 seconds')
        self.db, self.rotation_seconds, self.publish, self.publish_reveal = db, rotation_seconds, publish, publish_reveal
        self._published = set()
        self._publish_lock = __import__('asyncio').Lock()

    async def ensure_commitment(self): return await self.db.rotate_fair_seed(self.rotation_seconds)

    async def publish_commitment(self, value, force=False):
        async with self._publish_lock:
            if value in self._published and not force: return
            if force: self._published.discard(value)
            if self.publish is not None:
                await self.publish(value)
            self._published.add(value)

    async def publish_retired_reveals(self):
        if self.publish_reveal is None: return 0
        count=0
        for row in await self.db.pending_fair_reveals():
            await self.publish_reveal(row['commitment'],row['server_seed'],row['revealed_at'])
            await self.db.mark_fair_reveal_published(row['id']); count+=1
        return count

    async def allocate(self, uid: int, game: str, client_seed: str | None = None):
        seed = client_seed or str(uid)
        if not seed or len(seed) > 128: raise ValueError('client seed must contain 1..128 characters')
        current = await self.ensure_commitment()
        await self.publish_commitment(current['commitment'])
        return await self.db.allocate_fair_round(uid, game, seed, self.rotation_seconds)

    async def settle(self, round_id: str, outcome: str): await self.db.settle_fair_round(round_id, outcome)

    async def verify(self, round_id: str):
        row = await self.db.fair_round(round_id)
        if not row or not row['revealed_seed']: return None
        calculated = digest(row['revealed_seed'], row['client_seed'], row['nonce'], row['game'])
        commit_ok = commitment(row['revealed_seed']) == row['commitment']
        digest_ok = calculated == row['result_digest']
        outcome_ok = verify_game_outcome(row['game'], calculated, row['outcome'] or '')
        return {**dict(row), 'valid': commit_ok and digest_ok and outcome_ok,
                'commitment_valid': commit_ok, 'digest_valid': digest_ok, 'outcome_valid': outcome_ok}
