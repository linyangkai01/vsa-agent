import pytest

from vsa_agent.utils.image_resize import (
    dimensions_within_pixel_budget,
    resize_frame_to_pixel_budget,
)


@pytest.mark.parametrize(
    ("width", "height", "expected"),
    [
        (448, 448, (448, 448)),
        (1920, 1080, (597, 336)),
        (1080, 1920, (336, 597)),
    ],
)
def test_dimensions_stay_within_pixel_budget(width, height, expected):
    resized = dimensions_within_pixel_budget(width, height, 448 * 448)

    assert resized == expected
    assert resized[0] * resized[1] <= 448 * 448


@pytest.mark.parametrize(("width", "height", "max_pixels"), [(0, 1, 10), (1, 0, 10), (1, 1, 0)])
def test_dimensions_reject_invalid_values(width, height, max_pixels):
    with pytest.raises(ValueError):
        dimensions_within_pixel_budget(width, height, max_pixels)


def test_resize_frame_uses_area_interpolation():
    class Frame:
        shape = (1080, 1920, 3)

    class FakeCv2:
        INTER_AREA = "area"

        def __init__(self):
            self.call = None

        def resize(self, frame, dimensions, interpolation):
            self.call = (frame, dimensions, interpolation)
            return "resized"

    cv2 = FakeCv2()

    result = resize_frame_to_pixel_budget(Frame(), 448 * 448, cv2_module=cv2)

    assert result == "resized"
    assert cv2.call[1:] == ((597, 336), "area")


def test_resize_frame_leaves_small_image_unchanged():
    class Frame:
        shape = (100, 200, 3)

    class ForbiddenCv2:
        INTER_AREA = "area"

        def resize(self, *args, **kwargs):
            raise AssertionError("small image must not be resized")

    frame = Frame()

    assert resize_frame_to_pixel_budget(frame, 448 * 448, cv2_module=ForbiddenCv2()) is frame
