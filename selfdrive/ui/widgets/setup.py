import pyray as rl
from openpilot.common.time_helpers import system_time_valid
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.selfdrive.ui.widgets.pairing_dialog import PairingDialog
from openpilot.system.ui.lib.application import gui_app, FontWeight, FONT_SCALE
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.lib.wrap_text import wrap_text
from openpilot.system.ui.widgets import Widget
from openpilot.system.ui.widgets.confirm_dialog import alert_dialog
from openpilot.system.ui.widgets.button import Button, ButtonStyle
from openpilot.system.ui.widgets.label import Label


class SetupWidget(Widget):
  def __init__(self):
    super().__init__()
    self._open_settings_callback = None
    self._pair_device_btn = Button(lambda: tr("Pair device"), self._show_pairing, button_style=ButtonStyle.PRIMARY)
    self._open_settings_btn = Button(lambda: tr("Open"), lambda: self._open_settings_callback() if self._open_settings_callback else None,
                                     button_style=ButtonStyle.PRIMARY)
    self._firehose_label = Label(lambda: tr("🔥 Firehose Mode 🔥"), font_weight=FontWeight.MEDIUM, font_size=64)
    self._company_logo = None
    try:
      # Drop your logo file at selfdrive/assets/images/company_logo.png
      self._company_logo = gui_app.texture("images/company_logo.png", 360, 120, keep_aspect_ratio=True)
    except Exception:
      self._company_logo = None

  def set_open_settings_callback(self, callback):
    self._open_settings_callback = callback

  def _render(self, rect: rl.Rectangle):
    if not ui_state.prime_state.is_paired():
      self._render_registration(rect)
    else:
      self._render_firehose_prompt(rect)

  def _render_registration(self, rect: rl.Rectangle):
    """Render registration prompt."""

    # Layered background for a more intentional offroad style
    rl.draw_rectangle_rounded(rl.Rectangle(rect.x, rect.y, rect.width, rect.height), 0.035, 24, rl.Color(23, 29, 40, 255))
    rl.draw_rectangle_rounded(rl.Rectangle(rect.x + 12, rect.y + 12, rect.width - 24, rect.height - 24),
                              0.03, 20, rl.Color(33, 42, 56, 255))

    x = rect.x + 64
    y = rect.y + 34
    w = rect.width - 128

    y = self._render_brand_header(rect, y)

    # Title
    font = gui_app.font(FontWeight.BOLD)
    rl.draw_text_ex(font, tr("Finish Setup"), rl.Vector2(x, y), 72, 0, rl.WHITE)
    y += 102

    # Description
    desc = tr("Pair your device with comma connect (connect.comma.ai) and claim your comma prime offer.")
    light_font = gui_app.font(FontWeight.NORMAL)
    wrapped = wrap_text(light_font, desc, 46, int(w))
    for line in wrapped:
      rl.draw_text_ex(light_font, line, rl.Vector2(x, y), 46, 0, rl.Color(225, 233, 244, 255))
      y += 46 * FONT_SCALE

    button_rect = rl.Rectangle(x, y + 30, w, 200)
    self._pair_device_btn.render(button_rect)

  def _render_firehose_prompt(self, rect: rl.Rectangle):
    """Render firehose prompt widget."""

    rl.draw_rectangle_rounded(rl.Rectangle(rect.x, rect.y, rect.width, 520), 0.04, 20, rl.Color(23, 29, 40, 255))
    rl.draw_rectangle_rounded(rl.Rectangle(rect.x + 10, rect.y + 10, rect.width - 20, 500), 0.04, 20, rl.Color(33, 42, 56, 255))

    # Content margins (56, 40, 56, 40)
    x = rect.x + 56
    y = rect.y + 28
    w = rect.width - 112
    spacing = 42

    y = self._render_brand_header(rect, y, compact=True)

    # Title with fire emojis
    self._firehose_label.render(rl.Rectangle(rect.x, y, rect.width, 64))
    y += 64 + spacing

    # Description
    desc_font = gui_app.font(FontWeight.NORMAL)
    desc_text = tr("Maximize your training data uploads to improve KevellPilot's driving models.")
    wrapped_desc = wrap_text(desc_font, desc_text, 38, int(w))

    for line in wrapped_desc:
      rl.draw_text_ex(desc_font, line, rl.Vector2(x, y), 38, 0, rl.Color(225, 233, 244, 255))
      y += 40 * FONT_SCALE

    y += spacing

    # Open button
    button_height = 48 + 64  # font size + padding
    button_rect = rl.Rectangle(x, y, w, button_height)
    self._open_settings_btn.render(button_rect)

  def _render_brand_header(self, rect: rl.Rectangle, y: float, compact: bool = False) -> float:
    header_h = 86 if compact else 94
    pad_x = 56
    accent = rl.Color(78, 190, 255, 255)
    rail = rl.Color(29, 37, 49, 255)
    company_name = "KEVELL MOTORS"
    company_slogan = "A Companion"

    # Header rail + accent stripe
    rl.draw_rectangle_rounded(rl.Rectangle(rect.x + pad_x, y, rect.width - (2 * pad_x), header_h), 0.22, 16, rail)
    rl.draw_rectangle_rounded(rl.Rectangle(rect.x + pad_x, y, 18, header_h), 0.35, 16, accent)

    logo_x = rect.x + pad_x + 30
    logo_y = y + 12
    text_x = logo_x
    if self._company_logo is not None:
      # Light plate keeps dark logo variants legible against the dark header rail.
      plate = rl.Rectangle(logo_x - 6, logo_y - 4, 292, header_h - 16)
      rl.draw_rectangle_rounded(plate, 0.20, 10, rl.Color(246, 248, 250, 248))
      rl.draw_rectangle_rounded_lines(plate, 0.20, 10, rl.Color(102, 129, 150, 210))
      source = rl.Rectangle(0, 0, self._company_logo.width, self._company_logo.height)
      target = rl.Rectangle(logo_x, logo_y, 280, header_h - 24)
      rl.draw_texture_pro(self._company_logo, source, target, rl.Vector2(0, 0), 0, rl.WHITE)
      text_x = logo_x + 300

    title_font = gui_app.font(FontWeight.SEMI_BOLD)
    rl.draw_text_ex(title_font, tr(company_name), rl.Vector2(text_x, y + 18), 38, 0, rl.Color(217, 239, 255, 255))

    slogan_font = gui_app.font(FontWeight.NORMAL)
    rl.draw_text_ex(slogan_font, tr(company_slogan), rl.Vector2(text_x, y + 56), 28, 0, rl.Color(183, 212, 236, 255))

    return y + header_h + 26

  @staticmethod
  def _show_pairing():
    if not system_time_valid():
      dlg = alert_dialog(tr("Please connect to Wi-Fi to complete initial pairing"))
      gui_app.push_widget(dlg)
      return

    gui_app.push_widget(PairingDialog())
