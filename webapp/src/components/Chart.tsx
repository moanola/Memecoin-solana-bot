import { useEffect, useRef } from "react";
import { ColorType, createChart, type CandlestickData, type UTCTimestamp } from "lightweight-charts";
import { priceAxis } from "../format";
import type { Candle } from "../types";

export function PriceChart({ candles }: { candles: Candle[] }) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el || candles.length === 0) return;
    const chart = createChart(el, {
      autoSize: true,
      layout: {
        background: { type: ColorType.Solid, color: "transparent" },
        textColor: "#8d98aa",
        fontFamily: "IBM Plex Mono, ui-monospace, monospace",
      },
      grid: {
        vertLines: { color: "rgba(160,176,198,0.08)" },
        horzLines: { color: "rgba(160,176,198,0.08)" },
      },
      rightPriceScale: {
        borderColor: "rgba(160,176,198,0.16)",
        minimumWidth: 84,
        scaleMargins: { top: 0.14, bottom: 0.16 },
        entireTextOnly: true,
      },
      timeScale: {
        borderColor: "rgba(160,176,198,0.16)",
        timeVisible: true,
        secondsVisible: false,
        rightOffset: 4,
        fixLeftEdge: true,
        fixRightEdge: true,
      },
      localization: { priceFormatter: (p: number) => priceAxis(p) },
      crosshair: { vertLine: { color: "rgba(121,215,255,0.4)" }, horzLine: { color: "rgba(121,215,255,0.4)" } },
    });
    const series = chart.addCandlestickSeries({
      upColor: "#3ee0a0",
      downColor: "#ff5d73",
      borderVisible: false,
      wickUpColor: "#3ee0a0",
      wickDownColor: "#ff5d73",
      priceLineVisible: true,
      lastValueVisible: true,
      priceFormat: {
        type: "custom",
        minMove: 1e-12,
        formatter: (p: number) => priceAxis(p),
      },
    });
    const data: CandlestickData[] = candles.map((c) => ({
      time: c.time as UTCTimestamp,
      open: c.open,
      high: c.high,
      low: c.low,
      close: c.close,
    }));
    series.setData(data);
    chart.timeScale().fitContent();
    return () => chart.remove();
  }, [candles]);

  if (candles.length === 0) {
    return (
      <div className="card h-[280px] grid place-items-center text-mute text-sm">
        No price candles yet
      </div>
    );
  }
  return <div ref={ref} className="card h-[280px] overflow-hidden px-1" />;
}
