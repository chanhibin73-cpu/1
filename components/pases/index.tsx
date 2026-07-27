import ExamCountdown from '../components/ExamCountdown';
import styles from '../styles/Home.module.css'; // 後ほど新聞風CSSを作成

// 記事データの型定義
interface Article {
  id: string;
  title: string;
  content: string;
  publishDate: any;
  isBreaking: boolean;
}

export default function Home() {
  // 本来はここでFirebaseからデータを取得しますが、一旦サンプルデータを置いておきます
  const latestArticle: Article = {
    id: "1",
    title: "共通テスト 英語リーディングの傾向変化について",
    content: "最新の分析によると、読解量が昨年比で120パーセント増加しています。速読力の強化が必須となります...",
    publishDate: "2024/05/20",
    isBreaking: false
  };

  const archives: Article[] = [
    { id: "2", title: "主要国立大学の出願状況まとめ", content: "...", publishDate: "2024/05/16", isBreaking: false },
    { id: "3", title: "【速報】入試日程の一部変更について", content: "...", publishDate: "2024/05/15", isBreaking: true },
  ];

  return (
    <div className={styles.container}>
      <ExamCountdown />
      
      {/* 三本線メニュー（サイドバー）は別途実装 */}
      <nav className={styles.sidebarIcon}>☰</nav>

      <header className={styles.header}>
        <h1 className={styles.siteTitle}>入試日報新聞</h1>
      </header>

      <main className={styles.main}>
        {/* 最新の記事を大きく表示 */}
        <section className={styles.latestSection}>
          <div className={latestArticle.isBreaking ? styles.breakingBadge : styles.dateBadge}>
            {latestArticle.isBreaking ? "【速報】" : latestArticle.publishDate}
          </div>
          <h2 className={styles.latestTitle}>{latestArticle.title}</h2>
          <p className={styles.latestContent}>{latestArticle.content}</p>
        </section>

        <hr className={styles.divider} />

        {/* 過去記事のリスト表示 */}
        <section className={styles.archiveSection}>
          <h3>過去の記事</h3>
          <ul className={styles.archiveList}>
            {archives.map(article => (
              <li key={article.id} className={styles.archiveItem}>
                <span className={styles.archiveDate}>{article.publishDate}</span>
                <span className={styles.archiveTitle}>{article.title}</span>
              </li>
            ))}
          </ul>
        </section>
      </main>
    </div>
  );
}

