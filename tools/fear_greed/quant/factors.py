import logging
import numpy as np
import pandas as pd
from sklearn.decomposition import PCA

logger = logging.getLogger(__name__)


def extract_market_factor_pca(
    stocks_ret: pd.DataFrame,
    min_train: int = 60,
    refit_every: int = 21,
) -> pd.Series:
    """
    Trích xuất Market Factor (PC1) bằng expanding point-in-time PCA.

    Lý do dùng PCA thay VN-INDEX
    -----------------------------
    VN-INDEX là chỉ số vốn hóa — vài mã trụ (VIC, VHM, VCB...) chi phối
    hoàn toàn. PC1 của equal-weight returns mới phản ánh đúng co-movement
    của thị trường rộng.

    Các bước
    --------
    1. Tại mỗi refit point t, chỉ dùng dữ liệu [0, t) để chọn universe và fit PCA.
    2. Project tối đa ``refit_every`` phiên kế tiếp bằng model đã fit.
    3. Căn chỉnh dấu PC1 theo chiều equal-weight return của tập train.
    4. Rescale bằng độ lệch chuẩn equal-weight của tập train.

    Nhờ không fit trên toàn bộ lịch sử, việc append dữ liệu tương lai không làm
    thay đổi Market_Factor đã công bố trong quá khứ.
    """
    if min_train < 2:
        raise ValueError("min_train phải >= 2")
    if refit_every < 1:
        raise ValueError("refit_every phải >= 1")

    raw = stocks_ret.sort_index().replace([np.inf, -np.inf], np.nan)
    result = pd.Series(np.nan, index=raw.index, dtype=float, name="Market_Factor")
    explained_variance: list[float] = []

    for start in range(min_train, len(raw), refit_every):
        train = raw.iloc[:start]
        min_observations = max(2, int(np.ceil(len(train) * 0.5)))
        eligible = train.columns[train.notna().sum() >= min_observations]
        if len(eligible) < 2:
            continue

        train_clean = train[eligible].fillna(0.0)
        non_constant = train_clean.columns[train_clean.std(ddof=0) > 0]
        if len(non_constant) < 2:
            continue
        train_clean = train_clean[non_constant]

        pca = PCA(n_components=1)
        train_pc1 = pca.fit_transform(train_clean).ravel()
        train_ew = train_clean.mean(axis=1).to_numpy()

        sign = 1.0
        if np.std(train_pc1) > 0 and np.std(train_ew) > 0:
            corr = np.corrcoef(train_pc1, train_ew)[0, 1]
            if np.isfinite(corr) and corr < 0:
                sign = -1.0

        scale = 1.0
        pc1_std = float(np.std(train_pc1))
        ew_std = float(np.std(train_ew))
        if pc1_std > 0 and ew_std > 0:
            scale = ew_std / pc1_std

        end = min(start + refit_every, len(raw))
        prediction = raw.iloc[start:end][non_constant].fillna(0.0)
        projected = pca.transform(prediction).ravel() * sign * scale
        result.iloc[start:end] = projected
        explained_variance.append(float(pca.explained_variance_ratio_[0]))

    if explained_variance:
        logger.info(
            "Point-in-time PCA Market Factor — %d refits, latest PC1 explained %.1f %%",
            len(explained_variance),
            explained_variance[-1] * 100,
        )
    else:
        logger.warning("Point-in-time PCA Market Factor: không đủ dữ liệu để fit.")

    return result
