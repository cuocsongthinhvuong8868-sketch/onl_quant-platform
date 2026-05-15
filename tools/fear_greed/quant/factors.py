import logging
import numpy as np
import pandas as pd
from sklearn.decomposition import PCA

logger = logging.getLogger(__name__)


def extract_market_factor_pca(stocks_ret: pd.DataFrame) -> pd.Series:
    """
    Trích xuất Market Factor (PC1) từ ma trận lợi suất bằng PCA.

    Lý do dùng PCA thay VN-INDEX
    -----------------------------
    VN-INDEX là chỉ số vốn hóa — vài mã trụ (VIC, VHM, VCB...) chi phối
    hoàn toàn. PC1 của equal-weight returns mới phản ánh đúng co-movement
    của thị trường rộng.

    Các bước
    --------
    1. Loại cột thiếu > 50 % dữ liệu, fill NaN còn lại bằng 0.
    2. Fit PCA(n_components=1).
    3. Căn chỉnh dấu PC1 theo chiều equal-weight return.
    4. Rescale về đơn vị equal-weight std để dễ diễn giải.
    """
    clean = (
        stocks_ret.replace([np.inf, -np.inf], np.nan)
                  .dropna(axis=1, thresh=len(stocks_ret) // 2)
                  .fillna(0)
    )

    pca = PCA(n_components=1)
    pc1 = pca.fit_transform(clean).flatten()
    ew  = clean.mean(axis=1).values

    if np.corrcoef(pc1, ew)[0, 1] < 0:
        pc1 = -pc1

    pc1_std = pc1.std()
    if pc1_std > 0:
        pc1 = pc1 * (ew.std() / pc1_std)

    logger.info("PCA Market Factor — PC1 giải thích: %.1f %%",
                pca.explained_variance_ratio_[0] * 100)

    return pd.Series(pc1, index=stocks_ret.index, name="Market_Factor")
