import discord
import json
from io import StringIO
from discord.ext import commands
from cleaninty.ctr.simpledevice import SimpleCtrDevice
from cleaninty.ctr.soap.manager import CtrSoapManager
from cleaninty.ctr.soap import helpers
from cleaninty.nintendowifi.soapenvelopebase import SoapCodeError
from .abstractors.cleaninty_abstractor import cleaninty_abstractor
from .abstractors.db_abstractor import mySQL


class cleaninty_stuff(
    commands.Cog
):  # create a class for our cog that inherits from commands.Cog
    # this class is used to create a cog, which is a module that can be added to the bot

    def __init__(
        self, bot
    ):  # this is a special method that is called when the cog is loaded
        self.bot = bot

    @discord.slash_command(description="does a soap")
    async def doasoap(
        self,
        ctx: discord.ApplicationContext,
        jsonfile: discord.Option(discord.Attachment),
    ):
        try:
            await ctx.defer(ephemeral=True)
        except discord.errors.NotFound:
            return

        resultStr = "```"

        myDB = mySQL()

        # <json stuff>
        try:
            soap_json = await jsonfile.read()
            soap_json = soap_json.decode("utf-8")
            json.loads(soap_json)  # Validate the json, output useless
        except Exception:
            await ctx.respond(ephemeral=True, content="Failed to load json")
            return
        # </json stuff>

        try:
            dev = SimpleCtrDevice(json_string=soap_json)
            soapMan = CtrSoapManager(dev, False)
            helpers.CtrSoapCheckRegister(soapMan)
            cleaninty = cleaninty_abstractor()
        except Exception as e:
            await ctx.respond(
                ephemeral=True, content=f"Cleaninty error:\n```\n{e}\n```"
            )
            return

        soap_json = dev.serialize_json()
        source_json_object = json.loads(soap_json)
        source_json_region = source_json_object["region"]

        if source_json_region == "USA":
            source_region_change = "JPN"
            source_country_change = "JP"
            source_language_change = "ja"
        else:
            source_region_change = "USA"
            source_country_change = "US"
            source_language_change = "en"

        resultStr += "Attempting eShopRegionChange on source...\n"
        try:
            soap_json, resultStr = cleaninty.eshop_region_change(
                json_string=soap_json,
                region=source_region_change,
                country=source_country_change,
                language=source_language_change,
                result_string=resultStr,
            )

        except SoapCodeError as err:
            if not err.soaperrorcode == 602:
                ctx.respond(ephemeral=True, content=f"uh oh...\n\n{err}")
                return

            resultStr += "eShopRegionChange failed! running system transfer...\n"
            donor_json_name, donor_json = myDB.get_donor_json_ready_for_transfer()
            donor_json_object = json.loads(donor_json)

            donor_region_change = source_json_object["region"]
            donor_country_change = source_json_object["country"]
            donor_language_change = source_json_object["language"]

            if donor_json_object["region"] != source_json_object["region"]:
                resultStr += "Source and target regions do not match, changing...\n"
                donor_json, resultStr = cleaninty.eshop_region_change(
                    json_string=donor_json,
                    region=donor_region_change,
                    country=donor_country_change,
                    language=donor_language_change,
                    result_string=resultStr,
                )

            soap_json, donor_json, resultStr = cleaninty.do_system_transfer(
                source_json=soap_json, donor_json=donor_json, result_string=resultStr
            )
            donor_json = clean_json(donor_json)
            myDB.update_donor(donor_json_name, donor_json)
            resultStr += f"`{donor_json_name}` is now on cooldown\nDone!"

            helpers.CtrSoapCheckRegister(soapMan)
            soap_json = clean_json(soap_json)

        else:
            resultStr += (
                "eShopRegionChange successful, attempting account deletion...\n"
            )
            soap_json, resultStr = cleaninty.delete_eshop_account(
                json_string=soap_json, result_string=resultStr
            )

        helpers.CtrSoapCheckRegister(soapMan)
        soap_json = clean_json(soap_json)

        resultStr += "Done!\n```"
        await ctx.respond(
            ephemeral=True,
            content=resultStr,
            file=discord.File(fp=StringIO(soap_json), filename=jsonfile.filename),
        )
        # do stuff with soapman

    @discord.slash_command(description="check soap donor availability")
    async def soapcheck(self, ctx: discord.ApplicationContext):
        try:
            await ctx.defer(ephemeral=True)
        except discord.errors.NotFound:
            return

        myDB = mySQL()
        donors = myDB.read_table(table="donors")

        embed = discord.Embed(
            title="SOAP check",
            description="Checks what SOAP donors are available",
            color=discord.Color.blurple(), 
        )

        for i in range(len(donors)):
            name = donors[i][0]
            last_transfer = donors[i][2]
            embed.add_field(name=f"{name}", value=f"<t:{last_transfer + 604800}:R>")

        await ctx.respond(ephemeral=True, embed=embed)

    @discord.slash_command(
        description="uploads a donor soap json to be used for future soaps"
    )
    async def uploaddonorsoapjson(
        self,
        ctx: discord.ApplicationContext,
        donor_json_file: discord.Option(discord.Attachment),
    ):
        try:
            await ctx.defer(ephemeral=True)
        except discord.errors.NotFound:
            return

        if not donor_json_file.filename[-5:] == ".json":
            await ctx.respond(ephemeral=True, content="not a .json!")
            return

        try:
            donor_json = await donor_json_file.read()
            donor_json = donor_json.decode("utf-8")
            json.loads(donor_json)  # Validate the json, output useless
        except Exception:
            await ctx.respond(ephemeral=True, content="Failed to load json")
            return

        if donorcheck(donor_json):
            await ctx.respond(
                ephemeral=True,
                content="not a valid donor .json!\nif you believe this to be a mistake contact crudefern",
            )
            return

        donor_json = clean_json(donor_json)

        mySQL_DB = mySQL()
        mySQL_DB.write_donor(name=donor_json_file.filename, json=donor_json)

        await ctx.respond(
            ephemeral=True,
            content=f"`{donor_json_file.filename}` has been uploaded to the donor database\nwant to remove it? contact crudefern",
        )


def clean_json(json_string):
    json_object = json.loads(json_string)
    try:
        del json_object["titles"]
    except Exception:
        pass
    return json.dumps(json_object)


def donorcheck(input_json):
    """Checks for a valid donor .json as input"""
    try:
        input_json_obj = json.loads(input_json)
    except json.decoder.JSONDecodeError:
        return 1

    if len(input_json_obj["otp"]) != 344:
        return 1
    if len(input_json_obj["msed"]) != 428:
        return 1
    if len(input_json_obj["region"]) != 3:
        return 1
    return 0


def setup(bot):
    bot.add_cog(cleaninty_stuff(bot))
