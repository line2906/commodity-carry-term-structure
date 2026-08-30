import numpy as np
import pandas as pd
from tabulate import tabulate
from pandas.tseries.holiday import USFederalHolidayCalendar
from pandas.tseries.offsets import CustomBusinessDay, CustomBusinessMonthEnd
import matplotlib.pyplot as plt

BDay= CustomBusinessDay(calendar = USFederalHolidayCalendar())
BMend = CustomBusinessMonthEnd(calendar = USFederalHolidayCalendar())


class ExpiryCalendar:
    #Subtract 2 months from start and add about two to end  so expiration generates one extra contract either side
    def __init__(self, start, end):
        self.start = pd.Timestamp(start) - pd.DateOffset(months=2)
        self.end = pd.Timestamp(end) + pd.DateOffset(months=2)

    def expires(self, product):
        months = pd.date_range(self.start, self.end, freq="MS")
        if product == "CL":
            ref = months - pd.DateOffset(months=1) + pd.DateOffset(days=24)
            return pd.DatetimeIndex(
                [d - (3 * BDay if BDay.is_on_offset(d) else 4 * BDay) for d in ref]
            )
        if product == "NG":
            return pd.DatetimeIndex([d - 3 * BDay for d in months])
        if product in ("HO", "RB"):
            return pd.DatetimeIndex([d - BMend for d in months])
        raise ValueError(f"unknown product: {product}")
    def gap_day(self, product, near = 1, far = 2):
        exp= self.expires(product)
        #you want  want diff dates first then take the difference 
        #if you slide dates first, first row has nothing behind to difference against andomces out NaN
        gaps = exp.to_series().diff().shift(-1).dt.days
        return gaps

    def is_roll_date(self, product, dates):
        exp = self.expires(product)
        exp = exp[exp >= dates[0]]
        pos = dates.searchsorted(exp, side="right")
        pos = np.unique(pos[pos < len(dates)])
        flag = pd.Series(False, index=dates)
        flag.iloc[pos] = True
        return flag
class CarrySignal:
    #F1 is the front futures price while F2 is the back futures price 
    def __init__(self, F1, F2, cal):
        self.F1 = F1
        self.F2 = F2
        self.cal = cal
    def annualise(self):
        raw = self.F1 / self.F2 - 1
        out = {}
        for p in self.F1.columns:          # p is "CL", "HO", "NG", "RB"
            gap = self.cal.gap_day(p).reindex(self.F1.index, method="ffill")
            out[p] =  raw[p] *365/gap                 # raw[p] scaled by 365/gap
        return pd.DataFrame(out).replace([np.inf, -np.inf], np.nan)
class roll_adjusted_returns:
    def __init__(self, F1,F2, cal):
        self.F1 = F1
        self.F2 = F2
        self.cal = cal
    def roll_adjust(self):
        out = {}
        for p in self.F1.columns:
            roll_flags = self.cal.is_roll_date(p, self.F1.index)
            prev = np.where(roll_flags, self.F2[p].shift(), self.F1[p].shift())
            out[p] = self.F1[p] / prev -1
        #pd.Dataframe a two dimensaionable, size-mutable potentially hetrogenous tabular data
        return pd.DataFrame(out)

class Backtest:
    def __init__(self, sig, ret, cost_bps = 5.0):
        self.sig = sig
        self.ret = ret
        self.cost_bps = cost_bps 
    def weights(self):
        month_end = self.sig.resample("ME").last()
        rank = month_end.rank(axis=1, ascending=False)
        W = pd.DataFrame(0.0, index=month_end.index, columns=month_end.columns)
        W[rank <= 2] = 0.25
        W[rank >= 3] = -0.25
        return W
    def run(self):
        W = self.weights()
        Wd =  W.reindex(self.ret.index, method = 'ffill').shift(1)
        turnover = Wd.diff().abs().sum(axis=1)
        pnl = (Wd * self.ret).sum(axis=1) - turnover * self.cost_bps / 1e4
        return pnl.dropna()
    def metrics(self, pnl):
        eq = (1 + pnl).cumprod()
        yrs = (pnl.index[-1] - pnl.index[0]).days / 365.25
        return pd.Series({
            "Sharpe": pnl.mean() / pnl.std() * np.sqrt(252),
            "AnnRet": eq.iloc[-1] ** (1 / yrs) - 1,
            "Vol": pnl.std() * np.sqrt(252),
            "MaxDD": (eq / eq.cummax() - 1).min(),
        })
    def print_table(self,metrics, title = "Performance "):
        rows = [[k, f"{v:.3f}"] for k,v in metrics.items()]
        print(f"\n{title}")
        print(tabulate(rows, headers = ["Metrics", "Value"], tablefmt = "rounded_outline"))


def plot_correlation(ret):
    c = ret.corr()
    fig, ax = plt.subplots(figsize=(5, 4))
    im = ax.imshow(c, cmap="RdBu_r", vmin=-1, vmax=1)
    ax.set_xticks(range(len(c)), c.columns)
    ax.set_yticks(range(len(c)), c.index)
    for i in range(len(c)):
        for j in range(len(c)):
            ax.text(j, i, f"{c.iloc[i, j]:.2f}", ha="center", va="center")
    fig.colorbar(im)
    ax.set_title("Return correlation")
    fig.savefig("correlation.png", dpi=150, bbox_inches="tight")

def plot_seasonality(sig):
    m = sig.resample("ME").last()
    s = m.groupby(m.index.month).mean()
    fig, ax = plt.subplots(figsize = (4,7))
    im = ax.imshow(s, cmap="RdBu_r", vmin=-1, vmax=1)
    ax.set_xticks(range(len(s.columns)), s.columns)
    ax.set_yticks(range(len(s)), ["Jan","Feb","Mar","Apr","May","Jun",
                                  "Jul","Aug","Sep","Oct","Nov","Dec"])
    fig.colorbar(im)
    ax.set_title("Mean annualised carry by month")
    fig.savefig("seasonality.png", dpi=150, bbox_inches="tight")

def plot_equity(pnl, bench):
    eq = (1 + pnl).cumprod()
    eqb = (1 + bench).cumprod()
    dd = eq / eq.cummax() - 1
    fig, (ax1, ax2) = plt.subplots(2, 1, sharex=True, figsize=(9, 6))
    ax1.plot(eq, label="Carry L/S")
    ax1.plot(eqb, label="Equal weight")
    ax1.set_ylabel("Cumulative return")
    ax1.legend()
    ax2.fill_between(dd.index, dd * 100, 0, color="tomato")
    ax2.set_ylabel("Drawdown (%)")
    fig.savefig("equity.png", dpi=150, bbox_inches="tight")
        
df = pd.read_csv("eia_raw.csv", parse_dates=["period"])
df = df[df["product"].isin(["EPC0", "EPG0", "EPD2F", "EPMRR"])]
PRODUCT_MAP = {"EPC0": "CL", "EPG0": "NG", "EPD2F": "HO", "EPMRR": "RB"}
df["product"] = df["product"].map(PRODUCT_MAP)
df["value"] = df["value"].astype(float)
F1 = df[df["process"] == "PE1"].pivot(index="period", columns="product", values="value")
F2 = df[df["process"] == "PE2"].pivot(index="period", columns="product", values="value")
idx = F1.index.union(F2.index)
F1 = F1.reindex(idx).loc["2005-10-03":"2024-04-05"]
F2 = F2.reindex(idx).loc["2005-10-03":"2024-04-05"]
bad = (F1 <= 0) | (F2 <= 0)
F1, F2 = F1.mask(bad), F2.mask(bad)


def main():
    cal = ExpiryCalendar("2019-01-01", "2019-12-01")
    for p in ["CL", "NG", "HO", "RB"]:
        print(p, cal.expires(p)[:3])
    print(cal.gap_day("CL"))
    dates = pd.date_range("2019-01-01", "2019-03-31", freq="B")
    roll = cal.is_roll_date("CL", dates)
    print(roll.sum())
    print(roll[roll].index)
    print(F1.shape)
    print(F1.tail())
    print(F1.shape)
    print(F2.shape)
    cal = ExpiryCalendar(F1.index[0], F1.index[-1])
    sig = CarrySignal(F1, F2, cal).annualise()
    print(sig.iloc[-1].round(2))
    ret = roll_adjusted_returns(F1,F2,cal).roll_adjust()
    print(ret.abs().mean().mean())
    W = Backtest(sig, ret).weights()
    print(W.sum(axis=1).abs().max())
    print((W < 0).mean())
    bt = Backtest(sig, ret)
    pnl = bt.run()
    bt.print_table(bt.metrics(pnl), "CARRY L/S")
    bt.print_table(bt.metrics(ret.mean(axis=1)), "EQUAL WEIGHT")
    plot_correlation(ret)
    plot_seasonality(sig)
    plot_equity(pnl, ret.mean(axis=1))

if __name__ == "__main__":
    main()
