"""Chart rendering via pyecharts."""

from pyecharts.charts import Bar, Line, Pie
from pyecharts import options as opts


def render_chart(chart_type: str, columns: list[str], rows: list[list]) -> str | None:
    """Return an HTML string for the chart, or None if type unsupported."""
    if not rows or len(columns) < 1:
        return None

    chart_type = chart_type.lower().strip()

    if chart_type == "line":
        return _render_line(columns, rows)
    elif chart_type == "pie":
        return _render_pie(columns, rows)
    elif chart_type in ("bar", "column"):
        return _render_bar(columns, rows)
    elif chart_type == "table":
        return None  # Displayed as dataframe, no chart needed
    else:
        return _render_bar(columns, rows)


def _render_bar(columns: list[str], rows: list[list]) -> str:
    x_col = columns[0]
    y_col = columns[1] if len(columns) > 1 else columns[0]

    x_data = [str(row[0]) for row in rows]
    y_data = [row[1] if len(row) > 1 else row[0] for row in rows]

    bar = (
        Bar()
        .add_xaxis(x_data)
        .add_yaxis(y_col, y_data)
        .set_global_opts(
            title_opts=opts.TitleOpts(title=""),
            datazoom_opts=[opts.DataZoomOpts()],
            tooltip_opts=opts.TooltipOpts(trigger="axis"),
        )
        .set_series_opts(label_opts=opts.LabelOpts(is_show=False))
    )
    return bar.render_embed()


def _render_line(columns: list[str], rows: list[list]) -> str:
    x_data = [str(row[0]) for row in rows]

    line = Line()
    line.add_xaxis(x_data)

    for ci in range(1, len(columns)):
        line.add_yaxis(
            columns[ci],
            [row[ci] for row in rows],
            is_smooth=True,
            label_opts=opts.LabelOpts(is_show=False),
        )

    line.set_global_opts(
        title_opts=opts.TitleOpts(title=""),
        datazoom_opts=[opts.DataZoomOpts()],
        tooltip_opts=opts.TooltipOpts(trigger="axis"),
    )
    return line.render_embed()


def _render_pie(columns: list[str], rows: list[list]) -> str:
    data_pairs = [(str(row[0]), row[1] if len(row) > 1 else 1) for row in rows]

    pie = (
        Pie()
        .add("", data_pairs)
        .set_global_opts(
            title_opts=opts.TitleOpts(title=""),
            tooltip_opts=opts.TooltipOpts(trigger="item"),
        )
        .set_series_opts(label_opts=opts.LabelOpts(formatter="{b}: {c}"))
    )
    return pie.render_embed()
