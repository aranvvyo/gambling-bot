"""Reusable, user-scoped Discord component views."""
import discord
from services.ui import embed

class EmbedPager(discord.ui.View):
    def __init__(self,owner,pages,timeout=180):
        super().__init__(timeout=timeout);self.owner=owner;self.pages=pages;self.page=0;self.message=None
        self.previous.disabled=True;self.next.disabled=len(pages)<=1
    async def interaction_check(self,it):
        if it.user.id!=self.owner:
            await it.response.send_message(embed=embed('Private page','This menu belongs to another player.',state='error'),ephemeral=True);return False
        return True
    async def move(self,it,delta):
        self.page=max(0,min(len(self.pages)-1,self.page+delta));self.previous.disabled=self.page==0;self.next.disabled=self.page==len(self.pages)-1
        await it.response.edit_message(embed=self.pages[self.page],view=self)
    @discord.ui.button(label='Previous',style=discord.ButtonStyle.secondary,emoji='‹')
    async def previous(self,it,button):await self.move(it,-1)
    @discord.ui.button(label='Next',style=discord.ButtonStyle.secondary,emoji='›')
    async def next(self,it,button):await self.move(it,1)
    async def on_timeout(self):
        for item in self.children:item.disabled=True
        if self.message:
            try:await self.message.edit(view=self)
            except discord.HTTPException:pass
