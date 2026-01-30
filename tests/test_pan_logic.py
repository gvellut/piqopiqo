"""Tests for pan boundary logic in fullscreen overlay.

These tests verify the behavior of navigating between images of different sizes
while preserving zoom and center position, particularly around edge cases
with empty space calculations.
"""

from piqopiqo.pan_logic import (
    calculate_allowed_extra_from_current,
    calculate_current_space,
    calculate_effective_space_per_side,
    is_image_visible,
    update_allowed_extra_after_pan,
)

# Default PAN_EMPTY_SPACE value from config
PAN_EMPTY_SPACE = 300


class TestCalculateEffectiveSpacePerSide:
    """Tests for calculate_effective_space_per_side."""

    def test_no_extra_space_returns_base(self):
        """With no extra allowance, effective space equals base space."""
        allowed_extra = {"left": 0, "right": 0, "top": 0, "bottom": 0}
        result = calculate_effective_space_per_side(allowed_extra, PAN_EMPTY_SPACE)

        assert result["left"] == PAN_EMPTY_SPACE
        assert result["right"] == PAN_EMPTY_SPACE
        assert result["top"] == PAN_EMPTY_SPACE
        assert result["bottom"] == PAN_EMPTY_SPACE

    def test_extra_space_adds_to_base(self):
        """Extra allowance is added to base space."""
        allowed_extra = {"left": 100, "right": 200, "top": 0, "bottom": 50}
        result = calculate_effective_space_per_side(allowed_extra, PAN_EMPTY_SPACE)

        assert result["left"] == 400  # 300 + 100
        assert result["right"] == 500  # 300 + 200
        assert result["top"] == 300  # 300 + 0
        assert result["bottom"] == 350  # 300 + 50

    def test_missing_keys_default_to_zero(self):
        """Missing keys in allowed_extra default to zero extra."""
        allowed_extra = {"left": 100}  # Missing right, top, bottom
        result = calculate_effective_space_per_side(allowed_extra, PAN_EMPTY_SPACE)

        assert result["left"] == 400
        assert result["right"] == PAN_EMPTY_SPACE
        assert result["top"] == PAN_EMPTY_SPACE
        assert result["bottom"] == PAN_EMPTY_SPACE


class TestCalculateAllowedExtraFromCurrent:
    """Tests for calculate_allowed_extra_from_current."""

    def test_space_below_base_gives_zero_extra(self):
        """When current space is below base, no extra is allowed."""
        current_space = {"left": 100, "right": 200, "top": 50, "bottom": 299}
        result = calculate_allowed_extra_from_current(current_space, PAN_EMPTY_SPACE)

        assert result["left"] == 0
        assert result["right"] == 0
        assert result["top"] == 0
        assert result["bottom"] == 0

    def test_space_equal_to_base_gives_zero_extra(self):
        """When current space equals base, no extra is allowed."""
        current_space = {"left": 300, "right": 300, "top": 300, "bottom": 300}
        result = calculate_allowed_extra_from_current(current_space, PAN_EMPTY_SPACE)

        assert result["left"] == 0
        assert result["right"] == 0
        assert result["top"] == 0
        assert result["bottom"] == 0

    def test_space_above_base_gives_extra(self):
        """When current space exceeds base, the difference is allowed."""
        current_space = {"left": 500, "right": 400, "top": 300, "bottom": 350}
        result = calculate_allowed_extra_from_current(current_space, PAN_EMPTY_SPACE)

        assert result["left"] == 200  # 500 - 300
        assert result["right"] == 100  # 400 - 300
        assert result["top"] == 0  # 300 - 300
        assert result["bottom"] == 50  # 350 - 300

    def test_negative_space_gives_zero_extra(self):
        """Negative current space (image extends beyond) gives zero extra."""
        current_space = {"left": -100, "right": -50, "top": 0, "bottom": 300}
        result = calculate_allowed_extra_from_current(current_space, PAN_EMPTY_SPACE)

        assert result["left"] == 0
        assert result["right"] == 0
        assert result["top"] == 0
        assert result["bottom"] == 0


class TestUpdateAllowedExtraAfterPan:
    """Tests for update_allowed_extra_after_pan."""

    def test_pan_reducing_space_below_base_resets_extra(self):
        """Panning that reduces space below base resets that side's extra."""
        current_space = {"left": 250, "right": 400, "top": 300, "bottom": 350}
        allowed_extra = {"left": 200, "right": 100, "top": 50, "bottom": 50}

        result = update_allowed_extra_after_pan(
            current_space, allowed_extra, PAN_EMPTY_SPACE
        )

        # Left is now 250 < 300, so its extra is reset
        assert result["left"] == 0
        # Others are >= 300, so their extra is preserved
        assert result["right"] == 100
        assert result["top"] == 50
        assert result["bottom"] == 50

    def test_pan_keeping_space_above_base_preserves_extra(self):
        """Panning that keeps space at or above base preserves extra."""
        current_space = {"left": 300, "right": 500, "top": 350, "bottom": 400}
        allowed_extra = {"left": 200, "right": 200, "top": 100, "bottom": 100}

        result = update_allowed_extra_after_pan(
            current_space, allowed_extra, PAN_EMPTY_SPACE
        )

        # All spaces are >= 300, so all extras are preserved
        assert result["left"] == 200
        assert result["right"] == 200
        assert result["top"] == 100
        assert result["bottom"] == 100

    def test_pan_reducing_all_sides_resets_all(self):
        """Panning that reduces all sides below base resets all extras."""
        current_space = {"left": 100, "right": 150, "top": 200, "bottom": 250}
        allowed_extra = {"left": 500, "right": 400, "top": 300, "bottom": 200}

        result = update_allowed_extra_after_pan(
            current_space, allowed_extra, PAN_EMPTY_SPACE
        )

        assert result["left"] == 0
        assert result["right"] == 0
        assert result["top"] == 0
        assert result["bottom"] == 0


class TestIsImageVisible:
    """Tests for is_image_visible."""

    def test_image_fully_in_view(self):
        """Image completely within view is visible."""
        assert is_image_visible(100, 500, 100, 400, 800, 600)

    def test_image_partially_visible_left(self):
        """Image extending past left edge is still visible."""
        assert is_image_visible(-100, 200, 100, 400, 800, 600)

    def test_image_partially_visible_right(self):
        """Image extending past right edge is still visible."""
        assert is_image_visible(600, 1000, 100, 400, 800, 600)

    def test_image_partially_visible_top(self):
        """Image extending past top edge is still visible."""
        assert is_image_visible(100, 500, -100, 200, 800, 600)

    def test_image_partially_visible_bottom(self):
        """Image extending past bottom edge is still visible."""
        assert is_image_visible(100, 500, 400, 800, 800, 600)

    def test_image_completely_off_left(self):
        """Image completely off left edge is not visible."""
        assert not is_image_visible(-500, -100, 100, 400, 800, 600)

    def test_image_completely_off_right(self):
        """Image completely off right edge is not visible."""
        assert not is_image_visible(900, 1200, 100, 400, 800, 600)

    def test_image_completely_off_top(self):
        """Image completely off top edge is not visible."""
        assert not is_image_visible(100, 500, -400, -100, 800, 600)

    def test_image_completely_off_bottom(self):
        """Image completely off bottom edge is not visible."""
        assert not is_image_visible(100, 500, 700, 1000, 800, 600)

    def test_image_touching_left_edge_exactly(self):
        """Image with right edge at x=0 is not visible."""
        assert not is_image_visible(-200, 0, 100, 400, 800, 600)

    def test_image_touching_right_edge_exactly(self):
        """Image with left edge at view_width is not visible."""
        assert not is_image_visible(800, 1000, 100, 400, 800, 600)

    def test_image_with_right_edge_slightly_in_view(self):
        """Image with right edge just inside view is visible."""
        assert is_image_visible(-200, 1, 100, 400, 800, 600)


class TestCalculateCurrentSpace:
    """Tests for calculate_current_space."""

    def test_centered_image(self):
        """A centered image has equal space on opposite sides."""
        # Image 400x300 centered in 800x600 view
        result = calculate_current_space(200, 600, 150, 450, 800, 600)

        assert result["left"] == 200
        assert result["right"] == 200
        assert result["top"] == 150
        assert result["bottom"] == 150

    def test_image_shifted_left(self):
        """Image shifted left has more space on right."""
        result = calculate_current_space(100, 500, 150, 450, 800, 600)

        assert result["left"] == 100
        assert result["right"] == 300
        assert result["top"] == 150
        assert result["bottom"] == 150

    def test_image_extending_beyond_view(self):
        """Image extending beyond view has negative space."""
        result = calculate_current_space(-100, 900, -50, 650, 800, 600)

        assert result["left"] == -100
        assert result["right"] == -100  # 800 - 900
        assert result["top"] == -50
        assert result["bottom"] == -50  # 600 - 650


class TestNavigationScenarios:
    """Integration tests for navigation scenarios between different image sizes."""

    def test_navigate_large_to_small_preserves_center(self):
        """Navigating from large to small image with preserved center.

        Scenario:
        - Large image (2000x1500) zoomed in, panned so center is at screen (600, 400)
        - Navigate to small image (800x600)
        - The small image's center should also be at (600, 400)
        - This creates more empty space, which should be allowed
        """
        # Screen is 1200x800, small image 400x300 centered at (600, 400)
        # After positioning small image center at (600, 400):
        # Small image would be positioned at: left=200, right=1000, top=100, bottom=700
        # Current space: left=200, right=200, top=100, bottom=100

        # Actually, let's say the small image is 400x300 at the current zoom
        # If centered at (600, 400), it would be:
        # left = 600 - 200 = 400, right = 600 + 200 = 800
        # top = 400 - 150 = 250, bottom = 400 + 150 = 550

        current_space = {"left": 400, "right": 400, "top": 250, "bottom": 250}

        # This exceeds PAN_EMPTY_SPACE (300), so extra should be allowed
        allowed_extra = calculate_allowed_extra_from_current(
            current_space, PAN_EMPTY_SPACE
        )

        assert allowed_extra["left"] == 100  # 400 - 300
        assert allowed_extra["right"] == 100
        assert allowed_extra["top"] == 0  # 250 < 300
        assert allowed_extra["bottom"] == 0

    def test_navigate_back_to_large_preserves_position(self):
        """Navigating back to large image should preserve its position.

        Scenario:
        - Start with large image, zoom and pan
        - Navigate to small image (center preserved)
        - Navigate back to large image (center preserved)
        - The large image should be in its original position
        """
        # This is the key test case from the bug report

        # Initial state: large image with some pan
        # When navigating, allowed_extra is set based on the new image's space
        # The key is: allowed_extra is calculated AFTER positioning but BEFORE
        # clamping, so the center is never shifted during navigation

        # Step 1: Large image positioned at screen center (600, 400)
        # Large image fills most of screen: 50px space on left/right, 100px top/bottom
        large_img_space = {"left": 50, "right": 50, "top": 100, "bottom": 100}

        # Step 2: Navigate to small image, center at same position (600, 400)
        # Small image space: left=400, right=400, top=250, bottom=250
        small_img_space = {"left": 400, "right": 400, "top": 250, "bottom": 250}

        # Calculate allowed extra for small image
        small_allowed = calculate_allowed_extra_from_current(
            small_img_space, PAN_EMPTY_SPACE
        )
        assert small_allowed["left"] == 100
        assert small_allowed["right"] == 100

        # Calculate effective space for small image (used during clamping)
        small_effective = calculate_effective_space_per_side(
            small_allowed, PAN_EMPTY_SPACE
        )
        assert small_effective["left"] == 400
        assert small_effective["right"] == 400

        # The small image's space (400) is within effective space (400), so no clamping

        # Step 3: Navigate back to large image, center at same position (600, 400)
        # Large image space is back to: left=50, right=50, top=100, bottom=100

        # Calculate allowed extra for large image
        large_allowed = calculate_allowed_extra_from_current(
            large_img_space, PAN_EMPTY_SPACE
        )
        # Large image's space is all below 300, so no extra allowed
        assert large_allowed["left"] == 0
        assert large_allowed["right"] == 0

        # The large image fills the screen, clamping won't shift it
        # The center position is preserved!

    def test_pan_then_navigate_respects_reduced_space(self):
        """After panning to reduce space, navigation uses reduced limits.

        Scenario:
        - Small image with extra allowed space (e.g., left=500)
        - User pans to reduce left space to 200
        - This should reset left's extra to 0
        - When navigating to next image, left limit is back to 300
        """
        # Initial state after navigating to small image
        current_space = {"left": 500, "right": 300, "top": 300, "bottom": 300}
        allowed_extra = calculate_allowed_extra_from_current(
            current_space, PAN_EMPTY_SPACE
        )
        assert allowed_extra["left"] == 200  # 500 - 300

        # User pans left, reducing left space to 200
        after_pan_space = {"left": 200, "right": 400, "top": 300, "bottom": 300}

        # Update allowed extra after pan
        updated_extra = update_allowed_extra_after_pan(
            after_pan_space, allowed_extra, PAN_EMPTY_SPACE
        )

        # Left space (200) is below 300, so left extra is reset
        assert updated_extra["left"] == 0
        # Right space (400) is above 300, but original extra was 0, stays 0
        assert updated_extra["right"] == 0

    def test_offscreen_image_detected(self):
        """Test that completely offscreen images are detected."""
        # Large image was panned far to the right
        # New small image would be positioned entirely off the left edge
        view_width, view_height = 1200, 800

        # Small image (400x300) would be at: left=-800, right=-400
        assert not is_image_visible(-800, -400, 200, 500, view_width, view_height)

        # Small image just barely visible
        assert is_image_visible(-399, 1, 200, 500, view_width, view_height)
