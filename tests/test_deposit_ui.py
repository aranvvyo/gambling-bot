"""Ephemeral deposit view interactions exercised without a Discord network session."""
from types import SimpleNamespace
import logging

import pytest
from cogs.deposits import DepositAddressView


class Interaction:
    def __init__(self, user_id):
        self.user=SimpleNamespace(id=user_id)
        self.response=SimpleNamespace(send_message=self.send, defer=self.defer)
        self.followup=SimpleNamespace(send=self.followup_send)
        self.sent=[]; self.deferred=False
    async def send(self,*args,**kwargs): self.sent.append((args,kwargs))
    async def defer(self,*args,**kwargs): self.deferred=True
    async def followup_send(self,*args,**kwargs): self.sent.append((args,kwargs))


class Payments:
    def __init__(self,result=None,error=None): self.result=result; self.error=error; self.calls=[]
    async def reconcile(self,invoice):
        self.calls.append(invoice)
        if self.error: raise self.error
        return self.result


def build_view(payments):
    class DB:
        async def deposit(self,invoice):return {'invoice_id':invoice,'discord_id':42,'currency':'usdt@eth','requested_amount':'1000000','status':'created','credited':0,'verified_amount':0}
    bot=SimpleNamespace(payments=payments,db=DB(),settings=SimpleNamespace(currency_symbol='VC',casino_name='Test Vault',min_deposit='0.01'),logger=logging.getLogger('deposit-ui-test'),get_emoji=lambda _id:None)
    return DepositAddressView(bot,42,'0x'+'11'*20,'invoice123456','usdt@eth','1.00')


@pytest.mark.asyncio
async def test_copy_button_is_private_and_scoped_to_invoice_owner():
    view=build_view(Payments())
    assert [item.label for item in view.children]==['Copy Address','Check Payment']
    other=Interaction(7)
    await view.children[0].callback(other)
    assert other.sent[0][1]['ephemeral'] is True
    assert other.sent[0][1]['embed'].description and 'another player' in other.sent[0][1]['embed'].description
    owner=Interaction(42)
    await view.children[0].callback(owner)
    assert owner.sent[0][1]['ephemeral'] is True
    assert owner.sent[0][0]==('0x'+'11'*20,) and 'embed' not in owner.sent[0][1]


@pytest.mark.asyncio
async def test_status_button_checks_provider_and_handles_success_and_repeat():
    payments=Payments({'status':'completed','credited':True,'amount':123})
    view=build_view(payments); it=Interaction(42)
    await view.children[1].callback(it)
    assert it.deferred and payments.calls==['invoice123456']
    assert it.sent[0][1]['ephemeral'] is True
    assert 'credited' in it.sent[0][1]['embed'].description.lower()

    payments.result={'status':'completed','credited':False,'already_credited':True,'reason':''}
    repeat=Interaction(42); await view.children[1].callback(repeat)
    assert 'already credited' in repeat.sent[0][1]['embed'].description.lower()


@pytest.mark.asyncio
async def test_status_button_denies_other_users_and_reports_provider_outage_safely():
    payments=Payments({'status':'completed','credited':True,'amount':1})
    view=build_view(payments); other=Interaction(9)
    await view.children[1].callback(other)
    assert not payments.calls and other.sent[0][1]['ephemeral'] is True

    payments.error=TimeoutError('secret request details')
    owner=Interaction(42); await view.children[1].callback(owner)
    assert owner.deferred and owner.sent[0][1]['ephemeral'] is True
    assert 'could not verify' in owner.sent[0][1]['embed'].description.lower()
    assert 'secret request details' not in owner.sent[0][1]['embed'].description


def test_slash_deposit_choice_contains_only_the_three_distinct_provider_assets():
    from cogs.deposits import Deposits
    command=Deposits.deposit
    assert command.name=='deposit'
    choices={choice.value for parameter in command.parameters for choice in parameter.choices}
    assert choices=={'ltc','usdt@bnb','usdt@eth'}


@pytest.mark.asyncio
async def test_expired_view_disables_stale_controls():
    view=build_view(Payments())
    edited=[]
    view.message=SimpleNamespace(edit=lambda **kwargs: _record_edit(edited,kwargs))
    await view.on_timeout()
    assert all(item.disabled for item in view.children)
    assert len(edited)==1 and edited[0]['view'] is view

async def _record_edit(edited,kwargs):
    edited.append(kwargs)
