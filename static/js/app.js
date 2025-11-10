// Photo Analyzer JavaScript

// Lightbox functionality
function openImageModal(photoId, filename) {
    const modal = document.getElementById('imageModal');
    const modalImg = document.getElementById('modalImage');
    const modalFilename = document.getElementById('modalFilename');
    const loadingSpinner = document.getElementById('modalLoading');
    
    if (!modal || !modalImg) return;
    
    modal.style.display = 'block';
    loadingSpinner.style.display = 'block';
    modalImg.style.display = 'none';
    
    if (modalFilename) {
        modalFilename.textContent = filename || 'Photo';
    }
    
    // Load full image
    const fullImageUrl = `/photo/${photoId}/image`;
    modalImg.src = fullImageUrl;
    
    modalImg.onload = function() {
        loadingSpinner.style.display = 'none';
        modalImg.style.display = 'block';
    };
    
    modalImg.onerror = function() {
        loadingSpinner.style.display = 'none';
        modalImg.style.display = 'block';
        modalImg.src = `/photo/${photoId}/thumbnail`;
    };
}

function closeImageModal() {
    const modal = document.getElementById('imageModal');
    if (modal) {
        modal.style.display = 'none';
    }
}

// Close modal when clicking outside
window.onclick = function(event) {
    const modal = document.getElementById('imageModal');
    if (event.target === modal) {
        closeImageModal();
    }
}

// Close modal with ESC key
document.addEventListener('keydown', function(event) {
    if (event.key === 'Escape') {
        closeImageModal();
    }
});

// Admin functionality
function confirmAction(message) {
    return confirm(message);
}

// Face search functionality
function searchFaces(formData) {
    fetch('/api/faces/search', {
        method: 'POST',
        body: formData
    })
    .then(response => response.json())
    .then(data => {
        displaySearchResults(data);
    })
    .catch(error => {
        console.error('Search error:', error);
    });
}

function displaySearchResults(results) {
    const container = document.getElementById('searchResults');
    if (!container) return;
    
    container.innerHTML = '';
    
    if (results.length === 0) {
        container.innerHTML = '<p>No matching faces found.</p>';
        return;
    }
    
    results.forEach(result => {
        const item = document.createElement('div');
        item.className = 'search-result-item';
        item.innerHTML = `
            <img src="/photo/${result.photo_id}/thumbnail" alt="Photo">
            <div class="result-info">
                <p>Confidence: ${(result.confidence * 100).toFixed(1)}%</p>
                <a href="/photo/${result.photo_id}" class="btn">View Photo</a>
            </div>
        `;
        container.appendChild(item);
    });
}

// Load-more pagination (cursor-based) -------------------------------------------------
async function loadMorePhotos() {
    try {
        const paginationWrapper = document.querySelector('.pagination-wrapper');
        if (!paginationWrapper) return;

        // Prefer the explicit next-cursor data attribute if present
        let nextCursor = paginationWrapper.dataset.nextCursor;

        // Fallback: try to find a link with cursor in href
        if (!nextCursor) {
            const link = paginationWrapper.querySelector('a.page-link[href*="cursor="]');
            if (link) {
                const url = new URL(link.href, window.location.origin);
                nextCursor = url.searchParams.get('cursor');
            }
        }

        if (!nextCursor) return;

        const loadBtn = document.getElementById('loadMoreBtn');
        const spinner = document.getElementById('loadMoreSpinner');
        if (loadBtn) loadBtn.disabled = true;
        if (spinner) spinner.style.display = 'inline-block';

        // Build fetch URL using current location but with cursor param
        const fetchUrl = new URL(window.location.href);
        fetchUrl.searchParams.set('cursor', nextCursor);

        const res = await fetch(fetchUrl.toString(), { credentials: 'same-origin' });
        if (!res.ok) throw new Error('Network response was not ok');

        const text = await res.text();
        const parser = new DOMParser();
        const doc = parser.parseFromString(text, 'text/html');

        const newGrid = doc.querySelector('.photo-grid');
        const oldGrid = document.querySelector('.photo-grid');
        if (newGrid && oldGrid) {
            // Append new photo cards
            const nodes = Array.from(newGrid.children);
            nodes.forEach(n => oldGrid.appendChild(n));
        }

        // Update pagination wrapper's next cursor (if present) or remove button
        const newPagination = doc.querySelector('.pagination-wrapper');
        if (newPagination && newPagination.dataset && newPagination.dataset.nextCursor) {
            paginationWrapper.dataset.nextCursor = newPagination.dataset.nextCursor;
            if (loadBtn) loadBtn.disabled = false;
        } else {
            // No more pages; remove the button
            if (loadBtn && loadBtn.parentNode) loadBtn.parentNode.removeChild(loadBtn);
            if (spinner && spinner.parentNode) spinner.parentNode.removeChild(spinner);
        }

    } catch (err) {
        console.error('Failed to load more photos:', err);
        const loadBtn = document.getElementById('loadMoreBtn');
        if (loadBtn) loadBtn.disabled = false;
    } finally {
        const spinner = document.getElementById('loadMoreSpinner');
        if (spinner) spinner.style.display = 'none';
    }
}

function setupLoadMore() {
    const loadBtn = document.getElementById('loadMoreBtn');
    if (!loadBtn) return;
    loadBtn.addEventListener('click', loadMorePhotos);
}

document.addEventListener('DOMContentLoaded', function() {
    setupLoadMore();
});
