"""Configurable custom Discord emoji with Unicode fallbacks."""
import re
import unicodedata

DEFAULT_EMOJIS = {
    'achievement':'<:achivement:1564816726749741117>',
    'alert':'<:alert:1564816034802958557>',
    'failed':'<a:faild:1564817597894103252>',
    'info':'<a:info:1564820130888679605>',
    'loading':'<a:laoding:1564814465969561702>',
    'locked':'<a:locked:1564818651926896771>',
    'ltc':'<:ltc:1564815110671704306>',
    'usdt_bep20':'<:usdtbep20:1564815609663979691>',
    'usdt_erc20':'<:usdterc20:1564815757290774589>',
    'note':'<a:note:1564816505986617365>',
    'outcome':'<a:outcome:1564818319230632016>',
    'searching':'<:searching:1564816242072752128>',
    'success':'<a:tick:1564817901087629364>',
    'trash':'<a:trash:1564818960258437263>',
}
FALLBACKS = {
    'achievement':'🏆','alert':'⚠️','failed':'❌','info':'ℹ️','loading':'⏳','locked':'🔒',
    'ltc':'Ł','usdt_bep20':'🟢','usdt_erc20':'🔷','note':'📝','outcome':'🎲',
    'searching':'🔎','success':'✅','trash':'🗑️',
}
_CUSTOM = re.compile(r'^<(?P<animated>a?):(?P<name>[A-Za-z0-9_]{2,32}):(?P<id>[0-9]{17,20})>$')

def validate_emoji(value):
    if not isinstance(value,str): return False
    value=value.strip()
    if _CUSTOM.fullmatch(value): return True
    if not value or len(value)>16 or any(ch.isspace() for ch in value): return False
    # Accept emoji/pictograph sequences and flags, but reject arbitrary words.
    allowed={'So','Sk','Mn','Mc'}
    return (any(unicodedata.category(ch) in ('So','Sk') for ch in value)
            and all(unicodedata.category(ch) in allowed or ord(ch) in (0x200d,0xfe0f,0x20e3) for ch in value))

def resolve_emoji(bot,key):
    fallback=FALLBACKS.get(key,'✨')
    configured=getattr(bot,'emoji_map',{}).get(key,DEFAULT_EMOJIS.get(key,fallback))
    match=_CUSTOM.fullmatch(str(configured))
    if match:
        try:
            obj=bot.get_emoji(int(match.group('id'))) if bot else None
            return str(obj) if obj is not None else fallback
        except (AttributeError,TypeError,ValueError): return fallback
    return configured if validate_emoji(configured) else fallback
