import json
import discord
import os

class CogHandler:
    def __init__(self, bot):

        self.bot = bot
        self.cog_list = {}

        self.core_cogs = [
            "core.config.config",
            "core.tasks.tasks",
            "libs.misc.temp_utils_cog"
            # as the name suggests, this is temporary, will be moved/split up at some point, just not right now
        ]

        self.intent_list = []
        self.db_tables = []

    def preload_cog(self, key: str, filename: str, base="cogs") -> list[bool, Exception]:
        loader = None
        cog_config = {}
        if type(filename) is str and type(key) is str:
            try:
                try:
                    cog_config_file = open(f"./{base.replace('.', '/')}/{key.replace('.', '/')}/config_{filename}.json")
                    cog_config = json.loads(cog_config_file.read())
                    loader = cog_config.get("loader", None)
                except Exception:
                    pass  # probably not found

                if type(loader) is str and os.path.abspath(f"{base}/{loader}").startswith(
                        os.path.abspath(f"./{base.replace('.', '/')}/{key.replace('.', '/')}")):  # restrict paths
                    try:
                        loader = os.path.relpath(loader)
                        loader = loader.replace(chr(92), "/").replace("/", ".")
                        while ".." in loader:
                            loader = loader.replace("..", ".")
                    except Exception:
                        pass
                else:
                    loader = filename
                final = f"{base}.{key}.{loader}"
                self.cog_list[final] = cog_config
                if cog_config.get("intents", []):  # accounts for eval edge case
                    self.preloader_add_intents(cog_config["intents"], source=final)

                db_schema = cog_config.get("db_schema", {})
                if db_schema:
                    for key in db_schema:
                        table_schema = db_schema.get(key)
                        fields = table_schema.get("fields", [])
                        if fields and type(fields) is list:
                            self.db_tables.append({"name": key, "fields": fields})

                if final in self.core_cogs:
                    self.cog_list[final]["core"] = True
                else:
                    self.cog_list[final]["core"] = False
                return [True, None]
            except Exception as e:
                print(
                    f"\n\n\n[-]   {base}.{key}.{loader} could not be preloaded due to an error! See the error below for more details\n\n{type(e).__name__}: {e}\n\n\n")
                return [False, e]
        else:
            print(f"[X]    Ignoring {base}.{key} since it isn't text")
        return [False, None]

    def preloader_add_intents(self, intents: list[str], source: str = "") -> None:
        requested = []
        for intent in intents:
            if type(intent) is str:
                requested.append(intent)
        self.intent_list += requested
        print(f"{'An unspecified source' if not source else source} requested intents: {', '.join(requested)}")

    def make_intents(self, intents: list[str]) -> discord.Intents:
        base = discord.Intents.none()
        for intent in intents:
            try:
                if hasattr(base, intent):
                    setattr(base, intent, True)
                else:
                    raise Exception
            except Exception:
                print(f"Error setting intent '{intent}' since it is not valid")
        return base

    def load_cog(self, name) -> list[bool, Exception]:
        e = None
        if name in self.cog_list:
            try:
                for key in self.cog_list[name].get("config_keys", []):
                    data = self.cog_list[name]["config_keys"][key]
                    print(f"Sent config key {key} in for validation (requested by cog {name})")
                    self.bot.config_cog.register_config_key(key, data["validator"], data["description"])
                self.bot.load_extension(name)
                print(f'\n[+]    {name}')
            except Exception as e:
                return [False, e]
        else:
            print(f"\n\n\n[-]   {name} ignored since it wasn't registered")
            return [False, None]
        return [True, None]

    def load_cogs(self):
        for name in self.cog_list:
            result = self.load_cog(name)
            if not result[0]:
                print(f"\n\n\n[-]   {name} could not be loaded due to an error! " + f"See the error below for more details\n\n{type(result[1]).__name__}: {result[1]}" if result[1] else "")
                if name in self.core_cogs:
                    print(f"Exiting since a core cog could not be loaded...")
                    exit()

    def preload_core_cogs(self) -> None:
        """
        Non-negotiable.
        """

        print("Loading core cogs...")

        for cog in self.core_cogs:
            temp = cog.split(".")
            self.preload_cog(".".join(temp[1:-1]), temp[-1], base=temp[0])

    def preload_cogs(self, cog_list) -> None:
        """
        Procedure that loads all the cogs, from tree in config file
        """

        for key in cog_list:
            if type(cog_list[key]) is list:  # random validation checks yay
                for filename in cog_list[key]:
                    self.preload_cog(key, filename)
            else:
                print(
                    f"[X]    Ignoring flattened key cogs.{key} since it doesn't have a text list of filenames under <files> as required.")
