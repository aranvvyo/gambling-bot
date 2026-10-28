from decimal import Decimal
import pytest
from services.game_math import mines_multiplier,tower_multiplier,limbo_roll,blackjack_value,payout

def test_mines_multiplier_increases_and_validates():
 assert mines_multiplier(3,2)>mines_multiplier(3,1)>1
 with pytest.raises(ValueError):mines_multiplier(25,1)

def test_tower_math():
 assert tower_multiplier(2,2)==Decimal("3.96")
 assert tower_multiplier(3,3)>tower_multiplier(2,3)

def test_blackjack_aces_and_payout_cap():
 assert blackjack_value([1,9]) == 20
 assert blackjack_value([1,9,5]) == 15
 assert payout(100,Decimal("2.50"),200) == 200

def test_limbo_distribution_range():
 assert all(limbo_roll(Decimal("2")) >= Decimal("1.00") for _ in range(100))
