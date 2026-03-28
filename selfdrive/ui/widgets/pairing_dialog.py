import pyray as rl
import qrcode
import numpy as np
import time

from openpilot.common.api import Api
from openpilot.common.swaglog import cloudlog
from openpilot.common.params import Params
from openpilot.system.ui.widgets import Widget
from openpilot.system.ui.lib.application import FontWeight, gui_app
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.lib.wrap_text import wrap_text
from openpilot.system.ui.lib.text_measure import measure_text_cached
from openpilot.system.ui.widgets.button import IconButton
from openpilot.selfdrive.ui.ui_state import ui_state


COMPANY_NAME = "KEVELL MOTORS"
COMPANY_SLOGAN = "A Companion"


class PairingDialog(Widget):
  """Dialog for device pairing with QR code."""

  QR_REFRESH_INTERVAL = 300  # 5 minutes in seconds

  def __init__(self):
    super().__init__()
    self.params = Params()
    self.qr_texture: rl.Texture | None = None
    self.company_logo: rl.Texture | None = None
    self.last_qr_generation = float('-inf')
    self._close_btn = IconButton(gui_app.texture("icons/close.png", 80, 80))
    self._close_btn.set_click_callback(gui_app.pop_widget)
    try:
      self.company_logo = gui_app.texture("images/company_logo.png", 260, 90, keep_aspect_ratio=True)
    except Exception:
      self.company_logo = None

  def _get_pairing_url(self) -> str:
    try:
      dongle_id = self.params.get("DongleId") or ""
      token = Api(dongle_id).get_token({'pair': True})
    except Exception:
      cloudlog.exception("Failed to get pairing token")
      token = ""
    return f"https://connect.comma.ai/?pair={token}"

  def _generate_qr_code(self) -> None:
    try:
      qr = qrcode.QRCode(version=1, error_correction=qrcode.constants.ERROR_CORRECT_L, box_size=10, border=4)
      qr.add_data(self._get_pairing_url())
      qr.make(fit=True)

      pil_img = qr.make_image(fill_color="black", back_color="white").convert('RGBA')
      img_array = np.array(pil_img, dtype=np.uint8)

      if self.qr_texture and self.qr_texture.id != 0:
        rl.unload_texture(self.qr_texture)

      rl_image = rl.Image()
      rl_image.data = rl.ffi.cast("void *", img_array.ctypes.data)
      rl_image.width = pil_img.width
      rl_image.height = pil_img.height
      rl_image.mipmaps = 1
      rl_image.format = rl.PixelFormat.PIXELFORMAT_UNCOMPRESSED_R8G8B8A8

      self.qr_texture = rl.load_texture_from_image(rl_image)
    except Exception:
      cloudlog.exception("QR code generation failed")
      self.qr_texture = None

  def _check_qr_refresh(self) -> None:
    current_time = time.monotonic()
    if current_time - self.last_qr_generation >= self.QR_REFRESH_INTERVAL:
      self._generate_qr_code()
      self.last_qr_generation = current_time

  def _update_state(self):
    if ui_state.prime_state.is_paired():
      gui_app.pop_widget()

  def _render(self, rect: rl.Rectangle) -> int:
    rl.clear_background(rl.Color(214, 224, 236, 255))

    self._check_qr_refresh()

    margin = 70
    content_rect = rl.Rectangle(rect.x + margin, rect.y + margin, rect.width - 2 * margin, rect.height - 2 * margin)
    y = content_rect.y

    # Close button
    close_size = 80
    pad = 20
    close_rect = rl.Rectangle(content_rect.x - pad, y - pad, close_size + pad * 2, close_size + pad * 2)
    self._close_btn.render(close_rect)

    y += close_size + 18

    # Brand header
    brand_rect = rl.Rectangle(content_rect.x, y, content_rect.width, 90)
    self._render_brand_header(brand_rect)
    y += 102

    # Title
    title = tr("Pair your device to your KEVELL MOTORS account")
    title_font = gui_app.font(FontWeight.NORMAL)
    left_width = int(content_rect.width * 0.5 - 15)

    title_wrapped = wrap_text(title_font, title, 75, left_width)
    rl.draw_text_ex(title_font, "\n".join(title_wrapped), rl.Vector2(content_rect.x, y), 75, 0.0, rl.BLACK)
    y += len(title_wrapped) * 75 + 60

    # Two columns: instructions and QR code
    remaining_height = content_rect.height - (y - content_rect.y)
    right_width = content_rect.width // 2 - 20

    # Instructions
    self._render_instructions(rl.Rectangle(content_rect.x, y, left_width, remaining_height))

    # QR code
    qr_size = min(right_width, content_rect.height) - 40
    qr_x = content_rect.x + left_width + 40 + (right_width - qr_size) // 2
    qr_y = content_rect.y
    self._render_qr_code(rl.Rectangle(qr_x, qr_y, qr_size, qr_size))

    return -1

  def _render_instructions(self, rect: rl.Rectangle) -> None:
    instructions = [
      tr("Go to https://connect.comma.ai on your phone"),
      tr("Click \"add new device\" and scan the QR code on the right"),
      tr("Bookmark connect.comma.ai to your home screen for quick KEVELL access"),
    ]

    font = gui_app.font(FontWeight.BOLD)
    y = rect.y

    for i, text in enumerate(instructions):
      circle_radius = 25
      circle_x = rect.x + circle_radius + 15
      text_x = rect.x + circle_radius * 2 + 40
      text_width = rect.width - (circle_radius * 2 + 40)

      wrapped = wrap_text(font, text, 47, int(text_width))
      text_height = len(wrapped) * 47
      circle_y = y + text_height // 2

      # Circle and number
      rl.draw_circle(int(circle_x), int(circle_y), circle_radius, rl.Color(70, 70, 70, 255))
      number = str(i + 1)
      number_size = measure_text_cached(font, number, 30)
      rl.draw_text_ex(font, number, (int(circle_x - number_size.x // 2), int(circle_y - number_size.y // 2)), 30, 0, rl.WHITE)

      # Text
      rl.draw_text_ex(font, "\n".join(wrapped), rl.Vector2(text_x, y), 47, 0.0, rl.BLACK)
      y += text_height + 50

  def _render_qr_code(self, rect: rl.Rectangle) -> None:
    if not self.qr_texture:
      rl.draw_rectangle_rounded(rect, 0.1, 20, rl.Color(240, 240, 240, 255))
      error_font = gui_app.font(FontWeight.BOLD)
      rl.draw_text_ex(
        error_font, tr("QR Code Error"), rl.Vector2(rect.x + 20, rect.y + rect.height // 2 - 15), 30, 0.0, rl.RED
      )
      return

    source = rl.Rectangle(0, 0, self.qr_texture.width, self.qr_texture.height)
    rl.draw_texture_pro(self.qr_texture, source, rect, rl.Vector2(0, 0), 0, rl.WHITE)

  def _render_brand_header(self, rect: rl.Rectangle) -> None:
    rl.draw_rectangle_rounded(rect, 0.25, 16, rl.Color(33, 42, 56, 255))
    rl.draw_rectangle_rounded(rl.Rectangle(rect.x, rect.y, 16, rect.height), 0.35, 16, rl.Color(78, 190, 255, 255))

    text_x = rect.x + 28
    if self.company_logo is not None:
      # Light plate keeps dark logo variants legible against the dark header rail.
      plate = rl.Rectangle(rect.x + 18, rect.y + 6, 242, rect.height - 12)
      rl.draw_rectangle_rounded(plate, 0.20, 10, rl.Color(246, 248, 250, 248))
      rl.draw_rectangle_rounded_lines(plate, 0.20, 10, rl.Color(102, 129, 150, 210))
      source = rl.Rectangle(0, 0, self.company_logo.width, self.company_logo.height)
      target = rl.Rectangle(rect.x + 24, rect.y + 10, 230, rect.height - 20)
      rl.draw_texture_pro(self.company_logo, source, target, rl.Vector2(0, 0), 0, rl.WHITE)
      text_x = rect.x + 270

    title_font = gui_app.font(FontWeight.SEMI_BOLD)
    rl.draw_text_ex(title_font, tr(COMPANY_NAME), rl.Vector2(text_x, rect.y + 16), 34, 0, rl.Color(224, 241, 255, 255))

    slogan_font = gui_app.font(FontWeight.NORMAL)
    rl.draw_text_ex(slogan_font, tr(COMPANY_SLOGAN), rl.Vector2(text_x, rect.y + 52), 26, 0, rl.Color(181, 208, 232, 255))

  def __del__(self):
    if self.qr_texture and self.qr_texture.id != 0:
      rl.unload_texture(self.qr_texture)
    if self.company_logo and self.company_logo.id != 0:
      rl.unload_texture(self.company_logo)


if __name__ == "__main__":
  gui_app.init_window("pairing device")
  pairing = PairingDialog()
  gui_app.push_widget(pairing)
  try:
    for _ in gui_app.render():
      pass
  finally:
    del pairing
