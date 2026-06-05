import type {
  PortfolioCashDirection,
  PortfolioCorporateActionType,
  PortfolioFxRefreshResponse,
  PortfolioImportCommitResponse,
  PortfolioImportParseResponse,
  PortfolioPositionItem,
  PortfolioSide,
} from '../types/portfolio';
import { toDateInputValue } from './format';

export type FxRefreshFeedback = {
  tone: 'neutral' | 'success' | 'warning';
  text: string;
};

export type PortfolioAlertVariant = 'info' | 'success' | 'warning' | 'danger';

export function getTodayIso(): string {
  return toDateInputValue(new Date());
}

export function formatMoney(value: number | undefined | null, currency = 'CNY'): string {
  if (value == null || Number.isNaN(value)) return '--';
  return `${currency} ${Number(value).toLocaleString('zh-CN', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

export function formatPct(value: number | undefined | null): string {
  if (value == null || Number.isNaN(value)) return '--';
  return `${value.toFixed(2)}%`;
}

export function formatSignedPct(value: number | undefined | null): string {
  if (value == null || Number.isNaN(value)) return '--';
  const sign = value > 0 ? '+' : '';
  return `${sign}${value.toFixed(2)}%`;
}

export function hasPositionPrice(row: PortfolioPositionItem): boolean {
  return row.priceAvailable !== false && row.priceSource !== 'missing';
}

export function formatPositionPrice(row: PortfolioPositionItem): string {
  if (!hasPositionPrice(row)) return '--';
  return row.lastPrice.toFixed(4);
}

export function formatPositionMoney(value: number, row: PortfolioPositionItem): string {
  if (!hasPositionPrice(row)) return '--';
  return formatMoney(value, row.valuationCurrency);
}

export function getPositionPriceLabel(row: PortfolioPositionItem): string {
  if (!hasPositionPrice(row)) return 'Missing price';
  if (row.priceSource === 'realtime_quote') {
    return row.priceProvider ? `Real-time price · ${row.priceProvider}` : 'Real-time price';
  }
  if (row.priceSource === 'history_close') {
    return row.priceStale && row.priceDate ? `Close price · ${row.priceDate}` : 'Close price';
  }
  return row.priceSource || 'UnknownSource';
}

export function formatSideLabel(value: PortfolioSide): string {
  return value === 'buy' ? 'Buy' : 'Sell';
}

export function formatCashDirectionLabel(value: PortfolioCashDirection): string {
  return value === 'in' ? 'Inflow' : 'Outflow';
}

export function formatCorporateActionLabel(value: PortfolioCorporateActionType): string {
  return value === 'cash_dividend' ? 'Cash dividend' : 'Split/merge adjustment';
}

export function formatBrokerLabel(value: string, displayName?: string): string {
  if (displayName && displayName.trim()) return `${value}（${displayName.trim()}）`;
  if (value === 'huatai') return 'Huatai';
  if (value === 'citic') return 'CITIC';
  if (value === 'cmb') return 'CMB';
  return value;
}

export function buildFxRefreshFeedback(data: PortfolioFxRefreshResponse): FxRefreshFeedback {
  if (data.refreshEnabled === false) {
    return {
      tone: 'neutral',
      text: 'Online FX refresh is disabled.',
    };
  }

  if (data.pairCount === 0) {
    return {
      tone: 'neutral',
      text: 'There are no FX pairs to refresh in the current scope.',
    };
  }

  if (data.updatedCount > 0 && data.staleCount === 0 && data.errorCount === 0) {
    return {
      tone: 'success',
      text: `FX rates refreshed; updated ${data.updatedCount} pairs.`,
    };
  }

  const summary = `Updated ${data.updatedCount} pairs, still stale ${data.staleCount} 对，failed ${data.errorCount} pairs.`;
  if (data.staleCount > 0) {
    return {
      tone: 'warning',
      text: `Refresh attempted, but some currency pairs still use stale/fallback rates. ${summary}`,
    };
  }

  return {
    tone: 'warning',
    text: `Online refresh was not fully successful. ${summary}`,
  };
}

export function getFxRefreshFeedbackVariant(tone: FxRefreshFeedback['tone']): PortfolioAlertVariant {
  if (tone === 'success') return 'success';
  if (tone === 'warning') return 'warning';
  return 'info';
}

export function getCsvParseVariant(result: PortfolioImportParseResponse): PortfolioAlertVariant {
  return result.errorCount > 0 || result.skippedCount > 0 ? 'warning' : 'info';
}

export function getCsvCommitVariant(result: PortfolioImportCommitResponse, isDryRun: boolean): PortfolioAlertVariant {
  if (isDryRun) return 'info';
  return result.failedCount > 0 || result.duplicateCount > 0 ? 'warning' : 'success';
}
