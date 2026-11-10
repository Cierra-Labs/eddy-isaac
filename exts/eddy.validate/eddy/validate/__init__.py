"""eddy.validate — the Kit extension (IX5). A client of the engine's
`/v1/interop.*` routes; nothing of the engine runs inside Kit.

Menu: Eddy ▸ Validate selection — exports the selected prims' subtree
as USDA text (their stage's own layer, flattened for the selection),
imports it through `POST /v1/interop.import`, runs the truth solves the
user asked for on each rigid body (a stress check under the peak contact
force, the calibration of the pair's contact), paints `eddy:` attributes
on the prims through a sublayer the engine writes (`POST
/v1/interop.export`), and composes that sublayer over the stage.
"""
import omni.ext

try:
    import omni.usd
    from omni.kit.menu.utils import MenuItemDescription, add_menu_items, remove_menu_items
except Exception:  # pragma: no cover — outside Kit
    omni = None

from .client import validate_selection, write_sublayer_for_stage


class EddyValidateExtension(omni.ext.IExt):
    MENU = "Eddy"

    def on_startup(self, ext_id):
        self._menu = [
            MenuItemDescription(name="Validate selection", onclick_fn=lambda: validate_selection(omni.usd.get_context())),
            MenuItemDescription(name="Write Eddy sublayer for the stage", onclick_fn=lambda: write_sublayer_for_stage(omni.usd.get_context())),
        ]
        add_menu_items(self._menu, self.MENU)
        # HE5: the Replicator writer, when Replicator is enabled (it loads first: the optional
        # dependency in extension.toml); otherwise replicator_writer.register() later
        try:
            from .replicator_writer import register

            self._writer = register()
        except Exception as e:  # noqa: BLE001
            self._writer = f"not registered: {e}"

    def on_shutdown(self):
        remove_menu_items(self._menu, self.MENU)
