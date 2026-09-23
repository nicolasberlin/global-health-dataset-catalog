export default function ClassificationProgress({ progress }) {
    if (!progress?.total) return null;
    return <p>{progress.succeeded}/{progress.total} model responses saved.</p>;
}
