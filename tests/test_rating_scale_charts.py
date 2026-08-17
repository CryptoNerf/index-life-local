"""The charts follow the calendar grid's rating colours — until told not to.

Turning on "colour the day by its rating" is a statement about what a day
looks like, and the charts that draw days should honour it: a seven in the
grid and a seven on the spiral are the same green. But every chart can also
be given its own colour on the customization page, and a colour chosen on
purpose outranks one inherited from the grid.
"""
import pytest

from app.modules.customization import rating_scale as rs


ON = {'cube-scale-enabled': 'true'}
CHARTS = ['overview', 'spiral', 'rose', 'rhythm', 'river']


# ── when the mode applies at all ──────────────────────────────

def test_no_scale_while_the_grid_is_not_coloured_by_rating():
    assert rs.for_charts({}) is None
    assert rs.for_charts({'cube-scale-enabled': 'false'}) is None
    # Stops alone are not the switch — they exist whether or not it is on.
    assert rs.for_charts({'cube-scale-low': '#ff0000'}) is None


@pytest.mark.parametrize('chart', CHARTS)
def test_every_day_drawing_chart_follows_the_grid_by_default(chart):
    assert rs.for_charts(ON).color(chart, 7) is not None


def test_a_chart_that_draws_no_days_is_left_alone():
    """The ridgeline and the activity circles aren't days, so they keep
    whatever they had."""
    scale = rs.for_charts(ON)
    assert scale.color('ridgeline', 7) is None
    assert scale.color('activities-zoom', 7) is None


# ── the user's own colour wins ────────────────────────────────

@pytest.mark.parametrize('chart,key', list(rs.CHART_DAY_KEY.items()))
def test_a_chart_given_its_own_colour_stops_following_the_grid(chart, key):
    scale = rs.for_charts({**ON, key: '#123456'})

    assert scale.color(chart, 7) is None
    for other in (c for c in CHARTS if c != chart):
        assert scale.color(other, 7) is not None, (
            'one chart being customized must not silence the rest')


def test_the_global_chart_colour_counts_as_a_choice_about_charts():
    """"Make every chart this colour" is as deliberate as picking one."""
    scale = rs.for_charts({**ON, 'chart-color': '#0000ff'})

    assert all(scale.color(c, 7) is None for c in CHARTS)


def test_a_chart_key_that_is_not_the_day_surface_changes_nothing():
    """Recolouring the spiral's guide rings says nothing about its dots."""
    scale = rs.for_charts({**ON, 'spiral-guide-color': '#eeeeee',
                           'river-grid-color': '#eeeeee'})

    assert scale.color('spiral', 7) is not None
    assert scale.color('river', 7) is not None


# ── the colours themselves ────────────────────────────────────

def test_the_ends_and_the_middle_are_the_stops_themselves():
    scale = rs.for_charts({**ON, 'cube-scale-low': '#c0392b',
                           'cube-scale-mid': '#e0c14a',
                           'cube-scale-high': '#2a8f2a'})

    assert scale.color('overview', 1) == 'rgb(192, 57, 43)'
    assert scale.color('overview', 5.5) == 'rgb(224, 193, 74)'
    assert scale.color('overview', 10) == 'rgb(42, 143, 42)'


def test_an_average_lands_between_the_whole_ratings_either_side():
    """The rose and the rhythm grid paint averages: 6.4 must not be rounded
    onto a six or a seven."""
    scale = rs.for_charts(ON)
    six, mid, seven = (scale.color('rose', r) for r in (6, 6.4, 7))

    assert six != mid != seven


def test_the_grid_and_the_charts_agree_on_what_a_seven_is():
    """The whole point: both read the scale from the same place."""
    from app.modules.customization import context_processor as cp

    css = cp._cube_scale_rules(ON)
    grid_seven = css.split('.cube.filled.r7 { background: ')[1].split(';')[0]

    assert rs.for_charts(ON).color('spiral', 7) == grid_seven


def test_a_rating_outside_the_scale_is_clamped_not_extrapolated():
    scale = rs.for_charts(ON)

    assert scale.color('overview', 0) == scale.color('overview', 1)
    assert scale.color('overview', 99) == scale.color('overview', 10)


def test_a_day_without_a_rating_gets_no_colour():
    assert rs.for_charts(ON).color('overview', None) is None


# ── the legend describes the marks next to it ─────────────────

def test_the_legend_spans_the_whole_scale():
    scale = rs.for_charts(ON)
    legend = scale.legend('overview')

    assert len(legend) == 5
    assert legend[0] == scale.color('overview', 1)
    assert legend[-1] == scale.color('overview', 10)


def test_a_customized_chart_keeps_its_old_legend():
    scale = rs.for_charts({**ON, 'overview-heat-color': '#123456'})

    assert scale.legend('overview') == []
